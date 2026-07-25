"""Safe, provider-independent error normalization."""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    MISSING_CREDENTIAL = "missing_credential"
    AUTHENTICATION = "authentication"
    PERMISSION_DENIED = "permission_denied"
    RATE_LIMIT = "rate_limit"
    QUOTA_EXHAUSTED = "quota_exhausted"
    TIMEOUT = "timeout"
    NETWORK = "network"
    UNAVAILABLE_MODEL = "unavailable_model"
    CONTENT_FILTER = "content_filter"
    MALFORMED_RESPONSE = "malformed_response"
    SCHEMA_VALIDATION = "schema_validation"
    PROVIDER = "provider"


class ProviderError(RuntimeError):
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        provider: str,
        model: str,
        retryable: bool = False,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.provider = provider
        self.model = model
        self.retryable = retryable
        self.status_code = status_code

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "message": str(self),
            "provider": self.provider,
            "model": self.model,
            "retryable": self.retryable,
            "status_code": self.status_code,
        }


def missing_credential(provider: str, model: str, env_name: str) -> ProviderError:
    return ProviderError(
        ErrorCode.MISSING_CREDENTIAL,
        f"Missing credential: set {env_name} before calling {provider}.",
        provider=provider,
        model=model,
    )


def normalize_provider_exception(exc: Exception, *, provider: str, model: str) -> ProviderError:
    """Convert SDK-specific failures without leaking request headers or keys."""

    if isinstance(exc, ProviderError):
        return exc

    # HTTP clients commonly expose ``status_code`` while Google GenAI's
    # APIError exposes the same HTTP value as ``code``. Normalizing both keeps
    # transient 5xx/deadline failures retryable without importing any SDK.
    raw_status = getattr(exc, "status_code", None)
    if raw_status is None:
        raw_status = getattr(exc, "code", None)
    try:
        status = int(raw_status) if raw_status is not None else None
    except (TypeError, ValueError):
        status = None

    body = getattr(exc, "body", None)
    body_text = str(body or "").lower()
    metadata_text = " ".join(
        str(value or "").lower()
        for value in (
            getattr(exc, "status", None),
            getattr(exc, "message", None),
            getattr(exc, "details", None),
        )
    )
    chain_parts: list[str] = []
    current: BaseException | None = exc
    visited: set[int] = set()
    while current is not None and id(current) not in visited and len(visited) < 5:
        visited.add(id(current))
        chain_parts.append(type(current).__name__.lower())
        chain_parts.append(str(current).lower())
        current = current.__cause__ or current.__context__
    combined = " ".join([body_text, metadata_text, *chain_parts])

    if status == 401:
        code, safe, retryable = ErrorCode.AUTHENTICATION, "Provider rejected the credential.", False
    elif status == 403:
        code, safe, retryable = ErrorCode.PERMISSION_DENIED, "Credential has no access to this model.", False
    elif any(
        marker in combined
        for marker in (
            "failed_generation",
            "generated json does not match",
            "json_validate_failed",
        )
    ):
        code, safe, retryable = (
            ErrorCode.MALFORMED_RESPONSE,
            "Provider could not generate schema-valid JSON.",
            True,
        )
    elif "quota" in combined:
        code, safe, retryable = (
            ErrorCode.QUOTA_EXHAUSTED,
            "Provider quota was exhausted; retry after the provider resets it.",
            False,
        )
    elif status == 429 or "rate limit" in combined:
        code, safe, retryable = ErrorCode.RATE_LIMIT, "Provider rate limit or quota was reached.", True
    elif (
        status in {408, 504}
        or "timeout" in combined
        or "timed out" in combined
        or "deadline_exceeded" in combined
        or "deadline exceeded" in combined
    ):
        code, safe, retryable = ErrorCode.TIMEOUT, "Provider request timed out.", True
    elif "unavailable_model" in combined or "model_not_found" in combined or "not found" in combined:
        code, safe, retryable = ErrorCode.UNAVAILABLE_MODEL, "Configured model is unavailable.", False
    elif "content_filter" in combined or "safety" in combined or "blocked" in combined:
        code, safe, retryable = (
            ErrorCode.CONTENT_FILTER,
            "Provider blocked the response through a safety filter.",
            False,
        )
    elif status is not None and status >= 500:
        code, safe, retryable = ErrorCode.PROVIDER, "Provider service failed temporarily.", True
    elif "connect" in combined or "network" in combined or "dns" in combined:
        code, safe, retryable = ErrorCode.NETWORK, "Could not connect to provider.", True
    else:
        code, safe, retryable = ErrorCode.PROVIDER, "Provider request failed.", False

    return ProviderError(
        code,
        safe,
        provider=provider,
        model=model,
        retryable=retryable,
        status_code=status,
    )
