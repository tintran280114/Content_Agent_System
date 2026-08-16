"""Secure LinkedIn OAuth code exchange and encrypted token lifecycle."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlencode

import httpx

from .meta_auth import EncryptedTokenStore, ThreadsTokenRecord

LINKEDIN_AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
LINKEDIN_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
LINKEDIN_USERINFO_URL = "https://api.linkedin.com/v2/userinfo"
LINKEDIN_SCOPES = ("openid", "profile", "w_member_social")


class LinkedInAuthError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int | None = None) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(message)


class LinkedInHttpClient(Protocol):
    def get(self, url: str, **kwargs: Any) -> Any: ...
    def post(self, url: str, **kwargs: Any) -> Any: ...


def build_linkedin_authorization_url(*, client_id: str, redirect_uri: str, state: str) -> str:
    if not client_id.strip() or not redirect_uri.strip() or not state.strip():
        raise LinkedInAuthError(
            "invalid_linkedin_oauth_config",
            "LinkedIn Client ID, redirect URI, and OAuth state are required.",
        )
    return LINKEDIN_AUTH_URL + "?" + urlencode(
        {
            "response_type": "code",
            "client_id": client_id.strip(),
            "redirect_uri": redirect_uri.strip(),
            "state": state.strip(),
            "scope": " ".join(LINKEDIN_SCOPES),
        }
    )


class LinkedInOAuthClient:
    def __init__(self, *, client: LinkedInHttpClient | None = None, timeout_seconds: float = 30) -> None:
        self.client = client or httpx.Client()
        self.timeout_seconds = timeout_seconds

    def exchange_code(
        self,
        *,
        code: str,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
    ) -> tuple[str, str, int]:
        if not all(value.strip() for value in (code, client_id, client_secret, redirect_uri)):
            raise LinkedInAuthError("missing_linkedin_oauth_value", "LinkedIn OAuth fields are incomplete.")
        try:
            response = self.client.post(
                LINKEDIN_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code.strip(),
                    "client_id": client_id.strip(),
                    "client_secret": client_secret.strip(),
                    "redirect_uri": redirect_uri.strip(),
                },
                headers={"Accept": "application/json"},
                timeout=self.timeout_seconds,
            )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise LinkedInAuthError("linkedin_oauth_connection", "Could not reach LinkedIn OAuth.") from exc
        status = int(response.status_code)
        if status >= 400:
            oauth_error = ""
            try:
                # Keep the diagnostic constrained to LinkedIn's stable error
                # identifier.  Do not surface the response description because
                # providers may echo request details there.
                oauth_error = str(response.json().get("error", "")).strip()
            except (ValueError, AttributeError):
                pass
            diagnostic = f" OAuth error: {oauth_error}." if oauth_error else ""
            raise LinkedInAuthError(
                "linkedin_oauth_rejected",
                "LinkedIn rejected the authorization code or application configuration "
                f"(HTTP {status}).{diagnostic} Generate a fresh code and verify the exact redirect URI.",
                status_code=status,
            )
        try:
            payload = response.json()
            token = str(payload.get("access_token", "")).strip()
            expires_in = int(payload.get("expires_in", 0))
        except (ValueError, TypeError, AttributeError) as exc:
            raise LinkedInAuthError("invalid_linkedin_token_response", "LinkedIn returned an invalid token response.") from exc
        if not token or expires_in < 60:
            raise LinkedInAuthError("invalid_linkedin_token_response", "LinkedIn omitted the access token or expiry.")
        try:
            profile = self.client.get(
                LINKEDIN_USERINFO_URL,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                timeout=self.timeout_seconds,
            )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise LinkedInAuthError("linkedin_profile_connection", "Could not retrieve the LinkedIn member profile.") from exc
        profile_status = int(profile.status_code)
        if profile_status >= 400:
            raise LinkedInAuthError(
                "linkedin_profile_rejected",
                "LinkedIn did not return the authorized member profile.",
                status_code=profile_status,
            )
        try:
            subject = str(profile.json().get("sub", "")).strip()
        except (ValueError, AttributeError) as exc:
            raise LinkedInAuthError("invalid_linkedin_profile", "LinkedIn returned an invalid member profile.") from exc
        if not subject:
            raise LinkedInAuthError("invalid_linkedin_profile", "LinkedIn member profile omitted its subject identifier.")
        return token, f"urn:li:person:{subject}", expires_in


class LinkedInTokenManager:
    def __init__(
        self,
        *,
        env: Mapping[str, str] | None = None,
        store: EncryptedTokenStore | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.env = os.environ if env is None else env
        self.store = store
        self.now = now or (lambda: datetime.now(UTC))
        self._memory: dict[str, ThreadsTokenRecord] = {}

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None, *, base_dir: str | Path | None = None) -> "LinkedInTokenManager":
        runtime = os.environ if env is None else env
        return cls(env=runtime, store=EncryptedTokenStore.from_env(runtime, base_dir=base_dir))

    def save(self, credential_ref: str, *, access_token: str, person_urn: str, expires_in: int) -> ThreadsTokenRecord:
        if not access_token.strip() or not person_urn.startswith("urn:li:person:") or expires_in < 60:
            raise LinkedInAuthError("invalid_linkedin_token", "LinkedIn token, Person URN, or expiry is invalid.")
        record = ThreadsTokenRecord(
            credential_ref=credential_ref,
            access_token=access_token.strip(),
            user_id=person_urn,
            expires_at=self.now() + timedelta(seconds=expires_in),
            updated_at=self.now(),
        )
        self._memory[credential_ref] = record
        if self.store:
            self.store.put(record)
        return record

    def resolve(self, credential_ref: str) -> str:
        record = self._memory.get(credential_ref) or (self.store.get(credential_ref) if self.store else None)
        if record:
            if record.expires_at <= self.now():
                raise LinkedInAuthError("linkedin_token_expired", "LinkedIn token has expired; reconnect the account.")
            return record.access_token
        token = self.env.get(credential_ref, "").strip()
        if not token:
            raise LinkedInAuthError("missing_linkedin_token", f"Publishing credential '{credential_ref}' is not configured.")
        return token
