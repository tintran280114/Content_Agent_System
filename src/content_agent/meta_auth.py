"""Secure Meta token persistence and Threads OAuth token rotation."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken
from pydantic import Field

from .ai.models import StrictModel

THREADS_GRAPH_HOST = "https://graph.threads.net"
THREADS_AUTH_HOST = "https://threads.net/oauth/authorize"
DEFAULT_REFRESH_WINDOW_DAYS = 7
DEFAULT_HTTP_TIMEOUT_SECONDS = 30.0


class MetaAuthError(RuntimeError):
    """Safe OAuth/token error that never contains a credential or response body."""

    def __init__(self, code: str, message: str, *, status_code: int | None = None) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(message)


class ThreadsTokenRecord(StrictModel):
    credential_ref: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    access_token: str = Field(min_length=1)
    user_id: str | None = None
    expires_at: datetime
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def seconds_remaining(self, now: datetime | None = None) -> int:
        current = now or datetime.now(UTC)
        return max(0, int((self.expires_at - current).total_seconds()))


class ThreadsConnectionStatus(StrictModel):
    credential_ref: str
    configured: bool
    source: str
    expires_at: datetime | None = None
    seconds_remaining: int | None = None
    refresh_recommended: bool = False
    persistent_rotation: bool = False
    message: str


class EncryptedTokenStore:
    """Small encrypted local store; the encryption key remains in env/secrets."""

    def __init__(self, path: str | Path, encryption_key: str | bytes) -> None:
        self.path = Path(path)
        try:
            self.fernet = Fernet(
                encryption_key.encode("ascii") if isinstance(encryption_key, str) else encryption_key
            )
        except (ValueError, TypeError) as exc:
            raise MetaAuthError(
                "invalid_token_encryption_key",
                "CONTENT_AGENT_TOKEN_ENCRYPTION_KEY is not a valid Fernet key.",
            ) from exc

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        *,
        base_dir: str | Path | None = None,
    ) -> EncryptedTokenStore | None:
        runtime = os.environ if env is None else env
        key = runtime.get("CONTENT_AGENT_TOKEN_ENCRYPTION_KEY", "").strip()
        if not key:
            return None
        configured = runtime.get("CONTENT_AGENT_TOKEN_STORE", "artifacts/meta_tokens.enc").strip()
        path = Path(configured)
        if not path.is_absolute() and base_dir is not None:
            path = Path(base_dir) / path
        return cls(path, key)

    def _read_all(self) -> dict[str, ThreadsTokenRecord]:
        if not self.path.exists():
            return {}
        try:
            plaintext = self.fernet.decrypt(self.path.read_bytes())
            payload = json.loads(plaintext.decode("utf-8"))
            records = payload.get("records", {})
            if payload.get("version") != 1 or not isinstance(records, dict):
                raise ValueError("unsupported token-store payload")
            return {
                ref: ThreadsTokenRecord.model_validate(record)
                for ref, record in records.items()
            }
        except (OSError, UnicodeError, ValueError, InvalidToken, json.JSONDecodeError) as exc:
            raise MetaAuthError(
                "token_store_unreadable",
                "Encrypted Meta token store cannot be read; verify its key and file permissions.",
            ) from exc

    def get(self, credential_ref: str) -> ThreadsTokenRecord | None:
        return self._read_all().get(credential_ref)

    def put(self, record: ThreadsTokenRecord) -> None:
        records = self._read_all()
        records[record.credential_ref] = record
        payload = {
            "version": 1,
            "records": {
                ref: value.model_dump(mode="json")
                for ref, value in sorted(records.items())
            },
        }
        encrypted = self.fernet.encrypt(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            temporary.write_bytes(encrypted)
            os.replace(temporary, self.path)
        except OSError as exc:
            raise MetaAuthError(
                "token_store_write_failed",
                "Encrypted Meta token store could not be updated.",
            ) from exc


class ThreadsHttpClient(Protocol):
    def get(self, url: str, **kwargs: Any) -> Any:
        """Send one Threads GET request."""

    def post(self, url: str, **kwargs: Any) -> Any:
        """Send one Threads POST request."""


def _parse_expiry(value: str) -> datetime | None:
    normalized = value.strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise MetaAuthError(
            "invalid_token_expiry",
            "Threads token expiry must be an ISO-8601 timestamp, for example 2026-09-01T00:00:00Z.",
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


class ThreadsTokenManager:
    """Resolve, persist, and silently refresh unexpired long-lived tokens."""

    def __init__(
        self,
        *,
        env: Mapping[str, str] | None = None,
        store: EncryptedTokenStore | None = None,
        client: ThreadsHttpClient | None = None,
        now: Callable[[], datetime] | None = None,
        refresh_window_days: int | None = None,
    ) -> None:
        self.env = os.environ if env is None else env
        self.store = store
        self.client = client or httpx.Client(
            limits=httpx.Limits(max_keepalive_connections=5, keepalive_expiry=30.0)
        )
        self.now = now or (lambda: datetime.now(UTC))
        configured_window = self.env.get(
            "THREADS_TOKEN_REFRESH_DAYS",
            str(DEFAULT_REFRESH_WINDOW_DAYS),
        )
        try:
            self.refresh_window_days = (
                int(configured_window) if refresh_window_days is None else refresh_window_days
            )
        except ValueError as exc:
            raise MetaAuthError(
                "invalid_refresh_window",
                "THREADS_TOKEN_REFRESH_DAYS must be an integer.",
            ) from exc
        if self.refresh_window_days < 1 or self.refresh_window_days > 30:
            raise MetaAuthError(
                "invalid_refresh_window",
                "Threads refresh window must be between 1 and 30 days.",
            )
        self._memory: dict[str, ThreadsTokenRecord] = {}

    def _record(self, credential_ref: str) -> tuple[ThreadsTokenRecord | None, str]:
        if credential_ref in self._memory:
            return self._memory[credential_ref], "session"
        if self.store:
            stored = self.store.get(credential_ref)
            if stored:
                return stored, "encrypted_store"
        token = self.env.get(credential_ref, "").strip()
        if not token:
            return None, "missing"
        expiry = _parse_expiry(self.env.get(f"{credential_ref}_EXPIRES_AT", ""))
        if expiry is None:
            return (
                ThreadsTokenRecord(
                    credential_ref=credential_ref,
                    access_token=token,
                    expires_at=datetime.max.replace(tzinfo=UTC),
                ),
                "environment_expiry_unknown",
            )
        return (
            ThreadsTokenRecord(
                credential_ref=credential_ref,
                access_token=token,
                expires_at=expiry,
            ),
            "environment",
        )

    def status(self, credential_ref: str) -> ThreadsConnectionStatus:
        record, source = self._record(credential_ref)
        if not record:
            return ThreadsConnectionStatus(
                credential_ref=credential_ref,
                configured=False,
                source=source,
                persistent_rotation=bool(self.store),
                message="No Threads user access token is configured.",
            )
        unknown_expiry = source == "environment_expiry_unknown"
        remaining = None if unknown_expiry else record.seconds_remaining(self.now())
        refresh_recommended = (
            remaining is not None
            and remaining <= self.refresh_window_days * 24 * 60 * 60
            and remaining > 0
        )
        return ThreadsConnectionStatus(
            credential_ref=credential_ref,
            configured=True,
            source=source,
            expires_at=None if unknown_expiry else record.expires_at,
            seconds_remaining=remaining,
            refresh_recommended=refresh_recommended,
            persistent_rotation=bool(self.store),
            message=(
                "Token is configured, but expiry is unknown; automatic rotation needs an expiry timestamp."
                if unknown_expiry
                else "Threads token is configured and its lifecycle is managed."
            ),
        )

    def save_long_lived_token(
        self,
        credential_ref: str,
        *,
        access_token: str,
        expires_in: int,
        user_id: str | None = None,
    ) -> ThreadsTokenRecord:
        token = access_token.strip()
        if not token:
            raise MetaAuthError("missing_threads_token", "Threads access token is empty.")
        if expires_in < 60:
            raise MetaAuthError(
                "invalid_threads_expiry",
                "Threads token expiry is unexpectedly short.",
            )
        record = ThreadsTokenRecord(
            credential_ref=credential_ref,
            access_token=token,
            user_id=user_id,
            expires_at=self.now() + timedelta(seconds=expires_in),
            updated_at=self.now(),
        )
        self._memory[credential_ref] = record
        if self.store:
            self.store.put(record)
        return record

    def refresh(self, credential_ref: str) -> ThreadsTokenRecord:
        record, _ = self._record(credential_ref)
        if not record:
            raise MetaAuthError(
                "missing_threads_token",
                f"Publishing credential '{credential_ref}' is not configured.",
            )
        if record.expires_at <= self.now():
            raise MetaAuthError(
                "threads_token_expired",
                "Threads token has expired and cannot be silently refreshed; reconnect the account.",
            )
        try:
            response = self.client.get(
                f"{THREADS_GRAPH_HOST}/refresh_access_token",
                params={"grant_type": "th_refresh_token"},
                headers={
                    "Authorization": f"Bearer {record.access_token}",
                    "Accept": "application/json",
                },
                timeout=DEFAULT_HTTP_TIMEOUT_SECONDS,
            )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise MetaAuthError(
                "threads_refresh_connection",
                "Could not reach Threads while refreshing the token.",
            ) from exc
        status_code = int(response.status_code)
        if status_code >= 400:
            raise MetaAuthError(
                "threads_refresh_rejected",
                "Threads rejected token refresh; reconnect the account before it expires.",
                status_code=status_code,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise MetaAuthError(
                "invalid_threads_refresh_response",
                "Threads returned an invalid token-refresh response.",
                status_code=status_code,
            ) from exc
        token = str(payload.get("access_token", "")).strip() if isinstance(payload, dict) else ""
        try:
            expires_in = int(payload.get("expires_in", 0)) if isinstance(payload, dict) else 0
        except (TypeError, ValueError):
            expires_in = 0
        if not token or expires_in < 60:
            raise MetaAuthError(
                "invalid_threads_refresh_response",
                "Threads token-refresh response omitted the token or expiry.",
                status_code=status_code,
            )
        return self.save_long_lived_token(
            credential_ref,
            access_token=token,
            expires_in=expires_in,
            user_id=record.user_id,
        )

    def resolve(self, credential_ref: str) -> str:
        record, source = self._record(credential_ref)
        if not record:
            raise MetaAuthError(
                "missing_threads_token",
                f"Publishing credential '{credential_ref}' is not configured.",
            )
        current = self.now()
        if record.expires_at <= current:
            raise MetaAuthError(
                "threads_token_expired",
                "Threads token has expired; reconnect the account.",
            )
        refresh_at = record.expires_at - timedelta(days=self.refresh_window_days)
        if source != "environment_expiry_unknown" and current >= refresh_at:
            try:
                record = self.refresh(credential_ref)
            except MetaAuthError as exc:
                # A still-valid token is better than an outage caused only by a
                # transient refresh failure. Authentication rejection is not hidden.
                if exc.code != "threads_refresh_connection":
                    raise
        return record.access_token


class ThreadsOAuthClient:
    """Exchange an OAuth authorization code and immediately obtain a long-lived token."""

    def __init__(
        self,
        *,
        client: ThreadsHttpClient | None = None,
        timeout_seconds: float = DEFAULT_HTTP_TIMEOUT_SECONDS,
    ) -> None:
        self.client = client or httpx.Client()
        self.timeout_seconds = timeout_seconds

    def exchange_code(
        self,
        *,
        code: str,
        app_id: str,
        app_secret: str,
        redirect_uri: str,
    ) -> tuple[str, str, int]:
        values = {
            "code": code.strip(),
            "app_id": app_id.strip(),
            "app_secret": app_secret.strip(),
            "redirect_uri": redirect_uri.strip(),
        }
        if not all(values.values()):
            raise MetaAuthError(
                "threads_oauth_configuration",
                "Threads code, App ID, App Secret, and redirect URI are required.",
            )
        short_payload = self._request_json(
            "POST",
            f"{THREADS_GRAPH_HOST}/oauth/access_token",
            params={
                "client_id": values["app_id"],
                "client_secret": values["app_secret"],
                "code": values["code"],
                "grant_type": "authorization_code",
                "redirect_uri": values["redirect_uri"],
            },
        )
        short_token = str(short_payload.get("access_token", "")).strip()
        user_id = str(short_payload.get("user_id", "")).strip()
        if not short_token or not user_id:
            raise MetaAuthError(
                "invalid_threads_oauth_response",
                "Threads authorization response omitted the user ID or access token.",
            )
        long_payload = self._request_json(
            "GET",
            f"{THREADS_GRAPH_HOST}/access_token",
            params={
                "grant_type": "th_exchange_token",
                "client_secret": values["app_secret"],
            },
            headers={
                "Authorization": f"Bearer {short_token}",
                "Accept": "application/json",
            },
        )
        long_token = str(long_payload.get("access_token", "")).strip()
        try:
            expires_in = int(long_payload.get("expires_in", 0))
        except (TypeError, ValueError):
            expires_in = 0
        if not long_token or expires_in < 60:
            raise MetaAuthError(
                "invalid_threads_oauth_response",
                "Threads long-lived-token response omitted the token or expiry.",
            )
        return long_token, user_id, expires_in

    def _request_json(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, str],
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        try:
            if method == "POST":
                response = self.client.post(
                    url,
                    params=params,
                    headers=headers or {"Accept": "application/json"},
                    timeout=self.timeout_seconds,
                )
            else:
                response = self.client.get(
                    url,
                    params=params,
                    headers=headers or {"Accept": "application/json"},
                    timeout=self.timeout_seconds,
                )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise MetaAuthError(
                "threads_oauth_connection",
                "Could not reach Threads OAuth endpoints.",
            ) from exc
        status_code = int(response.status_code)
        if status_code >= 400:
            raise MetaAuthError(
                "threads_oauth_rejected",
                "Threads rejected the OAuth request. Check App ID, App Secret, code, and redirect URI.",
                status_code=status_code,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise MetaAuthError(
                "invalid_threads_oauth_response",
                "Threads returned an invalid OAuth response.",
                status_code=status_code,
            ) from exc
        if not isinstance(payload, dict):
            raise MetaAuthError(
                "invalid_threads_oauth_response",
                "Threads returned an unexpected OAuth response.",
                status_code=status_code,
            )
        return payload


def build_threads_authorization_url(
    *,
    app_id: str,
    redirect_uri: str,
    state: str,
    include_keyword_search: bool = False,
) -> str:
    """Build the Meta authorization URL without placing an app secret in it."""

    if not app_id.strip() or not redirect_uri.strip() or not state.strip():
        raise MetaAuthError(
            "threads_oauth_configuration",
            "Threads App ID, redirect URI, and state are required.",
        )
    scopes = ["threads_basic", "threads_content_publish"]
    if include_keyword_search:
        scopes.append("threads_keyword_search")
    query = urlencode(
        {
            "client_id": app_id.strip(),
            "redirect_uri": redirect_uri.strip(),
            "scope": ",".join(scopes),
            "response_type": "code",
            "state": state.strip(),
        }
    )
    return f"{THREADS_AUTH_HOST}?{query}"
