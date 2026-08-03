"""Guarded mock and Meta publishers selected from non-secret account policy."""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable
from uuid import UUID

import httpx

from .critics import render_post
from .meta_auth import EncryptedTokenStore, MetaAuthError, ThreadsTokenManager
from .platform import SQLiteRunStore
from .policy import AccountPolicy
from .workflow import PublishReceipt, PublishStatus, WorkflowState

PublishMode = Literal["dry-run", "live"]
SleepFunction = Callable[[float], None]


class PublishError(RuntimeError):
    """Safe delivery error that never includes credentials or response bodies."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        status_code: int | None = None,
    ) -> None:
        self.code = code
        self.retryable = retryable
        self.status_code = status_code
        super().__init__(message)


class CredentialResolver(Protocol):
    def resolve(self, credential_ref: str) -> str:
        """Resolve one policy-safe reference to a secret access token."""


class EnvironmentCredentialResolver:
    """Resolve tokens from environment variables without exposing their values."""

    def __init__(self, env: Mapping[str, str] | None = None) -> None:
        self.env = os.environ if env is None else env

    def resolve(self, credential_ref: str) -> str:
        value = self.env.get(credential_ref, "").strip()
        if not value:
            raise PublishError(
                "missing_publish_credential",
                f"Publishing credential '{credential_ref}' is not configured.",
            )
        return value


class ThreadsCredentialResolver:
    """Resolve Threads tokens with proactive long-lived-token rotation."""

    def __init__(
        self,
        env: Mapping[str, str] | None = None,
        *,
        client: Any | None = None,
    ) -> None:
        self.env = os.environ if env is None else env
        try:
            store = EncryptedTokenStore.from_env(self.env, base_dir=Path.cwd())
            self.manager = ThreadsTokenManager(
                env=self.env,
                store=store,
                client=client,
            )
        except MetaAuthError as exc:
            raise PublishError(exc.code, str(exc), status_code=exc.status_code) from exc

    def resolve(self, credential_ref: str) -> str:
        try:
            return self.manager.resolve(credential_ref)
        except MetaAuthError as exc:
            code = {
                "missing_threads_token": "missing_publish_credential",
                "threads_token_expired": "publish_authentication",
                "threads_refresh_rejected": "publish_authentication",
                "threads_refresh_connection": "publish_connection_error",
            }.get(exc.code, exc.code)
            raise PublishError(
                code,
                str(exc),
                retryable=exc.code == "threads_refresh_connection",
                status_code=exc.status_code,
            ) from exc


class HttpClient(Protocol):
    def get(
        self,
        url: str,
        *,
        params: Mapping[str, str],
        headers: Mapping[str, str],
        timeout: float,
    ) -> Any:
        """Send one HTTP GET request."""

    def post(
        self,
        url: str,
        *,
        data: Mapping[str, str],
        headers: Mapping[str, str],
        timeout: float,
    ) -> Any:
        """Send one form-encoded HTTP POST request."""


@runtime_checkable
class Publisher(Protocol):
    """Swappable publishing boundary used by orchestration and review services."""

    def publish(self, run_id: UUID | str) -> PublishReceipt:
        """Publish or block the authoritative current draft for one run."""


def _idempotency_key(run_id: UUID | str, draft_id: UUID | str, destination: str) -> str:
    raw = f"{run_id}\0{draft_id}\0{destination}".encode()
    return hashlib.sha256(raw).hexdigest()


def _receipt_from_row(row: dict[str, Any]) -> PublishReceipt:
    return PublishReceipt.model_validate_json(str(row["payload_json"]))


class _GuardedPublisher:
    ALLOWED_STATES = {WorkflowState.PASSED.value, WorkflowState.APPROVED.value}

    def __init__(self, store: SQLiteRunStore) -> None:
        self.store = store

    def _context(
        self,
        run_id: UUID | str,
    ) -> tuple[dict[str, Any], Any, AccountPolicy]:
        workflow = self.store.get_workflow(run_id)
        if not workflow:
            raise KeyError(f"workflow not found for run_id: {run_id}")
        draft = self.store.get_current_draft(run_id)
        policy = self.store.get_policy(run_id)
        return workflow, draft, policy

    def _existing(self, idempotency_key: str) -> PublishReceipt | None:
        row = self.store.get_publish_attempt_by_key(idempotency_key)
        return _receipt_from_row(row) if row else None

    def _save_initial(self, receipt: PublishReceipt) -> PublishReceipt:
        try:
            self.store.add_publish_attempt(receipt=receipt)
            return receipt
        except sqlite3.IntegrityError:
            existing = self._existing(receipt.idempotency_key)
            if existing is None:
                raise
            return existing

    def _set_workflow_state(
        self,
        run_id: UUID | str,
        *,
        state: WorkflowState,
        draft_id: UUID | str,
    ) -> None:
        workflow = self.store.get_workflow(run_id)
        self.store.update_workflow(
            run_id,
            state=state.value,
            current_draft_id=draft_id,
            rewrite_count=int(workflow["rewrite_count"]),
            expected_version=int(workflow["version"]),
        )


class MockPublisher(_GuardedPublisher):
    """Record a publish receipt without calling any social-platform API."""

    def publish(self, run_id: UUID | str) -> PublishReceipt:
        workflow, draft, policy = self._context(run_id)
        state = str(workflow["state"])
        allowed = state in self.ALLOWED_STATES
        destination = "mock"
        key_destination = destination if allowed else f"{destination}:blocked:{state}"
        key = _idempotency_key(run_id, draft.draft_id, key_destination)
        existing = self._existing(key)
        if existing:
            return existing
        topic_tag = policy.publishing.topic_tag or (
            policy.publishing.topic_tag_candidates[0]
            if policy.publishing.topic_tag_candidates
            else None
        )
        receipt = PublishReceipt(
            run_id=UUID(str(run_id)),
            draft_id=draft.draft_id,
            idempotency_key=key,
            status=PublishStatus.PUBLISHED if allowed else PublishStatus.BLOCKED,
            destination=destination,
            topic_tag=topic_tag,
            reason=(
                f"Mock publish accepted from workflow state '{state}'."
                if allowed
                else f"Publisher guard blocked workflow state '{state}'."
            ),
        )
        self._save_initial(receipt)
        if allowed:
            self._set_workflow_state(
                run_id,
                state=WorkflowState.PUBLISHED,
                draft_id=draft.draft_id,
            )
        return receipt


class _MetaPublisher(_GuardedPublisher):
    adapter: str
    graph_host: str
    version_env: str
    default_version: str

    def __init__(
        self,
        store: SQLiteRunStore,
        *,
        mode: PublishMode,
        credential_resolver: CredentialResolver | None = None,
        client: HttpClient | None = None,
        env: Mapping[str, str] | None = None,
        max_attempts: int = 3,
        base_backoff_seconds: float = 1.0,
        sleeper: SleepFunction = time.sleep,
    ) -> None:
        super().__init__(store)
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self.mode = mode
        self.env = os.environ if env is None else env
        self.credential_resolver = credential_resolver or EnvironmentCredentialResolver(self.env)
        self.client = client or httpx.Client(
            limits=httpx.Limits(max_keepalive_connections=5, keepalive_expiry=30.0)
        )
        self.max_attempts = max_attempts
        self.base_backoff_seconds = max(0.0, base_backoff_seconds)
        self.sleeper = sleeper
        try:
            self.request_timeout_seconds = float(
                self.env.get("META_REQUEST_TIMEOUT_SECONDS", "30")
            )
        except ValueError as exc:
            raise PublishError(
                "invalid_meta_timeout",
                "META_REQUEST_TIMEOUT_SECONDS must be a number.",
            ) from exc
        if not 5 <= self.request_timeout_seconds <= 120:
            raise PublishError(
                "invalid_meta_timeout",
                "META_REQUEST_TIMEOUT_SECONDS must be between 5 and 120 seconds.",
            )

    def _version(self) -> str:
        version = self.env.get(self.version_env, self.default_version).strip()
        if not re.fullmatch(r"v\d+\.\d+", version):
            raise PublishError(
                "invalid_graph_version",
                f"{self.version_env} must use a value such as v25.0.",
            )
        return version

    def _prepare(
        self,
        run_id: UUID | str,
    ) -> tuple[dict[str, Any], Any, AccountPolicy, str, PublishReceipt | None]:
        workflow, draft, policy = self._context(run_id)
        if policy.publishing.adapter != self.adapter:
            raise PublishError(
                "publisher_route_mismatch",
                f"Policy adapter '{policy.publishing.adapter}' cannot use {self.adapter}.",
            )
        destination = f"{self.adapter}:{policy.publishing.target_id}"
        key_destination = destination if self.mode == "live" else f"{destination}:dry-run"
        key = _idempotency_key(run_id, draft.draft_id, key_destination)
        existing = self._existing(key)
        if existing:
            if existing.status in {PublishStatus.PUBLISHED, PublishStatus.DRY_RUN}:
                return workflow, draft, policy, key, existing
            if existing.status in {PublishStatus.FAILED, PublishStatus.BLOCKED}:
                key = _idempotency_key(run_id, draft.draft_id, f"{key_destination}:{uuid4().hex[:8]}")
            else:
                raise PublishError(
                    "publish_attempt_already_reserved",
                    f"Publish attempt '{key[:12]}' is already {existing.status.value}.",
                )
        state = str(workflow["state"])
        allowed_states = set(self.ALLOWED_STATES)
        if self.mode == "live":
            allowed_states.add(WorkflowState.DRY_RUN.value)
        if state not in allowed_states:
            raise PublishError(
                "publisher_guard_blocked",
                f"Publisher guard blocked workflow state '{state}'.",
            )
        return workflow, draft, policy, key, None

    def _reserve(
        self,
        run_id: UUID | str,
        *,
        draft_id: UUID,
        destination: str,
        idempotency_key: str,
    ) -> PublishReceipt:
        pending = PublishReceipt(
            run_id=UUID(str(run_id)),
            draft_id=draft_id,
            idempotency_key=idempotency_key,
            destination=destination,
            status=PublishStatus.PENDING,
            attempt_count=0,
            reason="Publish attempt reserved before external delivery.",
        )
        saved = self._save_initial(pending)
        if saved.publish_id != pending.publish_id:
            raise PublishError(
                "publish_attempt_already_reserved",
                f"Publish attempt '{idempotency_key[:12]}' is already reserved.",
            )
        return pending

    def _post(
        self,
        url: str,
        *,
        data: Mapping[str, str],
        token: str,
    ) -> tuple[dict[str, Any], int, int]:
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
        last_status: int | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self.client.post(
                    url,
                    data=data,
                    headers=headers,
                    timeout=self.request_timeout_seconds,
                )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt >= self.max_attempts:
                    raise PublishError(
                        "publish_connection_error",
                        "Meta API could not be reached after bounded retries.",
                        retryable=True,
                    ) from exc
                self.sleeper(self.base_backoff_seconds * (2 ** (attempt - 1)))
                continue
            last_status = int(response.status_code)
            if last_status < 400:
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise PublishError(
                        "invalid_publish_response",
                        "Meta API returned a non-JSON success response.",
                        status_code=last_status,
                    ) from exc
                if not isinstance(payload, dict):
                    raise PublishError(
                        "invalid_publish_response",
                        "Meta API returned an unexpected success payload.",
                        status_code=last_status,
                    )
                return payload, last_status, attempt
            retryable = last_status == 429 or last_status >= 500
            if not retryable or attempt >= self.max_attempts:
                code = "publish_authentication" if last_status in {401, 403} else "meta_api_error"
                message = (
                    "Meta rejected the publishing credential or required permission."
                    if last_status in {401, 403}
                    else f"Meta API request failed with HTTP {last_status}."
                )
                raise PublishError(
                    code,
                    message,
                    retryable=retryable,
                    status_code=last_status,
                )
            self.sleeper(self.base_backoff_seconds * (2 ** (attempt - 1)))
        raise PublishError(
            "meta_api_error",
            f"Meta API request failed with HTTP {last_status}.",
            retryable=True,
            status_code=last_status,
        )

    def _get(
        self,
        url: str,
        *,
        params: Mapping[str, str],
        token: str,
    ) -> tuple[dict[str, Any], int, int]:
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
        last_status: int | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self.client.get(
                    url,
                    params=params,
                    headers=headers,
                    timeout=self.request_timeout_seconds,
                )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt >= self.max_attempts:
                    raise PublishError(
                        "publish_connection_error",
                        "Meta API could not be reached after bounded retries.",
                        retryable=True,
                    ) from exc
                self.sleeper(self.base_backoff_seconds * (2 ** (attempt - 1)))
                continue
            last_status = int(response.status_code)
            if last_status < 400:
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise PublishError(
                        "invalid_publish_response",
                        "Meta API returned a non-JSON success response.",
                        status_code=last_status,
                    ) from exc
                if not isinstance(payload, dict):
                    raise PublishError(
                        "invalid_publish_response",
                        "Meta API returned an unexpected success payload.",
                        status_code=last_status,
                    )
                return payload, last_status, attempt
            retryable = last_status == 429 or last_status >= 500
            if not retryable or attempt >= self.max_attempts:
                code = "publish_authentication" if last_status in {401, 403} else "meta_api_error"
                message = (
                    "Meta rejected the publishing credential or required permission."
                    if last_status in {401, 403}
                    else f"Meta API request failed with HTTP {last_status}."
                )
                raise PublishError(
                    code,
                    message,
                    retryable=retryable,
                    status_code=last_status,
                )
            self.sleeper(self.base_backoff_seconds * (2 ** (attempt - 1)))
        raise PublishError(
            "meta_api_error",
            f"Meta API request failed with HTTP {last_status}.",
            retryable=True,
            status_code=last_status,
        )

    def _dry_run(
        self,
        run_id: UUID | str,
        *,
        pending: PublishReceipt,
        topic_tag: str | None = None,
    ) -> PublishReceipt:
        receipt = pending.model_copy(
            update={
                "status": PublishStatus.DRY_RUN,
                "attempt_count": 0,
                "topic_tag": topic_tag,
                "reason": (f"Dry-run validated {self.adapter} delivery; no external API was called."),
            }
        )
        self.store.update_publish_attempt(receipt=receipt)
        self._set_workflow_state(
            run_id,
            state=WorkflowState.DRY_RUN,
            draft_id=receipt.draft_id,
        )
        return receipt

    def _failed(
        self,
        pending: PublishReceipt,
        exc: PublishError,
        *,
        attempt_count: int,
    ) -> None:
        failed = pending.model_copy(
            update={
                "status": PublishStatus.FAILED,
                "http_status": exc.status_code,
                "attempt_count": attempt_count,
                "reason": str(exc),
            }
        )
        self.store.update_publish_attempt(receipt=failed)


class FacebookPagePublisher(_MetaPublisher):
    """Publish text posts to a Facebook Page feed."""

    adapter = "facebook_page"
    graph_host = "https://graph.facebook.com"
    version_env = "META_GRAPH_API_VERSION"
    default_version = "v25.0"

    def publish(self, run_id: UUID | str) -> PublishReceipt:
        _, draft, policy, key, existing = self._prepare(run_id)
        if existing:
            return existing
        destination = f"{self.adapter}:{policy.publishing.target_id}"
        pending = self._reserve(
            run_id,
            draft_id=draft.draft_id,
            destination=destination,
            idempotency_key=key,
        )
        if self.mode == "dry-run":
            try:
                self._version()
            except PublishError as exc:
                self._failed(pending, exc, attempt_count=0)
                raise
            return self._dry_run(run_id, pending=pending)
        attempt_count = 0
        try:
            token = self.credential_resolver.resolve(str(policy.publishing.credential_ref))
            url = f"{self.graph_host}/{self._version()}/{policy.publishing.target_id}/feed"
            payload, status_code, attempt_count = self._post(
                url,
                data={"message": render_post(draft)},
                token=token,
            )
            remote_post_id = str(payload.get("id", "")).strip()
            if not remote_post_id:
                raise PublishError(
                    "invalid_publish_response",
                    "Facebook Page API response did not contain a post id.",
                    status_code=status_code,
                )
        except PublishError as exc:
            self._failed(pending, exc, attempt_count=max(attempt_count, 1))
            raise
        receipt = pending.model_copy(
            update={
                "status": PublishStatus.PUBLISHED,
                "remote_post_id": remote_post_id,
                "http_status": status_code,
                "attempt_count": attempt_count,
                "reason": "Facebook Page post published successfully.",
            }
        )
        self.store.update_publish_attempt(receipt=receipt)
        self._set_workflow_state(
            run_id,
            state=WorkflowState.PUBLISHED,
            draft_id=draft.draft_id,
        )
        return receipt


class ThreadsPublisher(_MetaPublisher):
    """Create and publish a text container through the Threads API."""

    adapter = "threads"
    graph_host = "https://graph.threads.net"
    version_env = "THREADS_GRAPH_API_VERSION"
    default_version = "v1.0"

    def __init__(
        self,
        store: SQLiteRunStore,
        *,
        mode: PublishMode,
        credential_resolver: CredentialResolver | None = None,
        client: HttpClient | None = None,
        env: Mapping[str, str] | None = None,
        max_attempts: int = 3,
        base_backoff_seconds: float = 1.0,
        sleeper: SleepFunction = time.sleep,
    ) -> None:
        runtime = os.environ if env is None else env
        active_client = client or httpx.Client(
            limits=httpx.Limits(max_keepalive_connections=5, keepalive_expiry=30.0)
        )
        resolver = credential_resolver or ThreadsCredentialResolver(
            runtime,
            client=active_client,
        )
        super().__init__(
            store,
            mode=mode,
            credential_resolver=resolver,
            client=active_client,
            env=runtime,
            max_attempts=max_attempts,
            base_backoff_seconds=base_backoff_seconds,
            sleeper=sleeper,
        )

    @staticmethod
    def _topic_tag_candidates(policy: AccountPolicy) -> list[str]:
        configured = policy.publishing.topic_tag_candidates
        fallback = policy.publishing.topic_tag
        candidates = list(configured)
        if fallback and fallback.casefold() not in {item.casefold() for item in candidates}:
            candidates.insert(0, fallback)
        return candidates

    def _select_topic_tag(
        self,
        *,
        policy: AccountPolicy,
        token: str,
        version: str,
    ) -> tuple[str | None, int]:
        candidates = self._topic_tag_candidates(policy)
        fallback = policy.publishing.topic_tag or (candidates[0] if candidates else None)
        if not policy.publishing.trend_search:
            return fallback, 0

        best_tag = fallback
        best_score = -1
        total_attempts = 0
        since = str(int(time.time()) - 24 * 60 * 60)
        for candidate in candidates:
            payload, _, attempts = self._get(
                f"{self.graph_host}/{version}/keyword_search",
                params={
                    "q": candidate,
                    "search_type": "RECENT",
                    "search_mode": "TAG",
                    "fields": "id,topic_tag,timestamp",
                    "limit": "25",
                    "since": since,
                },
                token=token,
            )
            total_attempts += attempts
            results = payload.get("data")
            if not isinstance(results, list):
                raise PublishError(
                    "invalid_publish_response",
                    "Threads keyword search returned an unexpected payload.",
                )
            score = len(results)
            if score > best_score:
                best_tag = candidate
                best_score = score
        return best_tag, total_attempts

    def publish(self, run_id: UUID | str) -> PublishReceipt:
        _, draft, policy, key, existing = self._prepare(run_id)
        if existing:
            return existing
        destination = f"{self.adapter}:{policy.publishing.target_id}"
        pending = self._reserve(
            run_id,
            draft_id=draft.draft_id,
            destination=destination,
            idempotency_key=key,
        )
        if self.mode == "dry-run":
            try:
                self._version()
            except PublishError as exc:
                self._failed(pending, exc, attempt_count=0)
                raise
            draft = self.store.get_current_draft(run_id)
            draft_tag = getattr(draft, "topic_tag", None)
            candidates = self._topic_tag_candidates(policy)
            topic_tag = (
                draft_tag
                or policy.publishing.topic_tag
                or (candidates[0] if candidates else None)
            )
            return self._dry_run(run_id, pending=pending, topic_tag=topic_tag)
        total_attempts = 0
        try:
            token = self.credential_resolver.resolve(str(policy.publishing.credential_ref))
            version = self._version()
            draft = self.store.get_current_draft(run_id)
            if getattr(draft, "topic_tag", None):
                topic_tag = draft.topic_tag.strip()
                search_attempts = 0
            else:
                topic_tag, search_attempts = self._select_topic_tag(
                    policy=policy,
                    token=token,
                    version=version,
                )
            total_attempts += search_attempts
            base_url = f"{self.graph_host}/{version}/{policy.publishing.target_id}"
            container_data = {
                "media_type": "TEXT",
                "text": render_post(draft),
            }
            if topic_tag:
                container_data["topic_tag"] = topic_tag
            container, _, attempts = self._post(
                f"{base_url}/threads",
                data=container_data,
                token=token,
            )
            total_attempts += attempts
            container_id = str(container.get("id", "")).strip()
            if not container_id:
                raise PublishError(
                    "invalid_publish_response",
                    "Threads API response did not contain a container id.",
                )
            published, status_code, attempts = self._post(
                f"{base_url}/threads_publish",
                data={"creation_id": container_id},
                token=token,
            )
            total_attempts += attempts
            remote_post_id = str(published.get("id", "")).strip()
            if not remote_post_id:
                raise PublishError(
                    "invalid_publish_response",
                    "Threads API response did not contain a post id.",
                    status_code=status_code,
                )
        except PublishError as exc:
            self._failed(pending, exc, attempt_count=max(total_attempts, 1))
            raise
        receipt = pending.model_copy(
            update={
                "status": PublishStatus.PUBLISHED,
                "remote_post_id": remote_post_id,
                "topic_tag": topic_tag,
                "http_status": status_code,
                "attempt_count": total_attempts,
                "reason": (
                    f"Threads text post published successfully with topic tag '{topic_tag}'."
                    if topic_tag
                    else "Threads text post published successfully."
                ),
            }
        )
        self.store.update_publish_attempt(receipt=receipt)
        self._set_workflow_state(
            run_id,
            state=WorkflowState.PUBLISHED,
            draft_id=draft.draft_id,
        )
        return receipt


class PolicyPublisherRouter:
    """Select a publisher from the persisted account policy."""

    def __init__(
        self,
        store: SQLiteRunStore,
        *,
        mode: PublishMode = "dry-run",
        credential_resolver: CredentialResolver | None = None,
        client: HttpClient | None = None,
        env: Mapping[str, str] | None = None,
        max_attempts: int = 3,
        base_backoff_seconds: float = 1.0,
        sleeper: SleepFunction = time.sleep,
    ) -> None:
        if mode not in {"dry-run", "live"}:
            raise ValueError("publish mode must be 'dry-run' or 'live'")
        self.store = store
        self.mode = mode
        self.credential_resolver = credential_resolver
        self.client = client
        self.env = env
        self.max_attempts = max_attempts
        self.base_backoff_seconds = base_backoff_seconds
        self.sleeper = sleeper

    def publish(self, run_id: UUID | str) -> PublishReceipt:
        policy = self.store.get_policy(run_id)
        if policy.publishing.adapter == "mock":
            return MockPublisher(self.store).publish(run_id)
        publisher_class = {
            "facebook_page": FacebookPagePublisher,
            "threads": ThreadsPublisher,
        }[policy.publishing.adapter]
        publisher = publisher_class(
            self.store,
            mode=self.mode,
            credential_resolver=self.credential_resolver,
            client=self.client,
            env=self.env,
            max_attempts=self.max_attempts,
            base_backoff_seconds=self.base_backoff_seconds,
            sleeper=self.sleeper,
        )
        return publisher.publish(run_id)
