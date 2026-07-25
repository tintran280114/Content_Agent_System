"""Conservative application quotas enforced before each provider request."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from .ai.errors import ErrorCode, ProviderError
from .platform import SQLiteRunStore


@dataclass(frozen=True)
class QuotaBudget:
    max_requests_per_day: int
    max_tokens_per_day: int

    def __post_init__(self) -> None:
        if self.max_requests_per_day < 1 or self.max_tokens_per_day < 1:
            raise ValueError("quota limits must be positive integers")


DEFAULT_BUDGETS = {
    "gemini": QuotaBudget(max_requests_per_day=100, max_tokens_per_day=100_000),
    "groq": QuotaBudget(max_requests_per_day=300, max_tokens_per_day=100_000),
    "github_models": QuotaBudget(max_requests_per_day=100, max_tokens_per_day=100_000),
}


class QuotaManager:
    """Track daily requests/tokens per provider-model and stop before overrun."""

    def __init__(
        self,
        store: SQLiteRunStore,
        *,
        budgets: Mapping[str, QuotaBudget] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.store = store
        self.budgets = dict(budgets or self.from_environment())
        self.clock = clock or (lambda: datetime.now(UTC))

    @staticmethod
    def from_environment() -> dict[str, QuotaBudget]:
        budgets: dict[str, QuotaBudget] = {}
        for provider, default in DEFAULT_BUDGETS.items():
            prefix = f"CONTENT_AGENT_{provider.upper()}"
            try:
                max_requests = int(
                    os.environ.get(
                        f"{prefix}_MAX_REQUESTS_PER_DAY",
                        default.max_requests_per_day,
                    )
                )
                max_tokens = int(
                    os.environ.get(
                        f"{prefix}_MAX_TOKENS_PER_DAY",
                        default.max_tokens_per_day,
                    )
                )
            except ValueError as exc:
                raise ValueError(f"invalid integer quota configuration for {provider}") from exc
            budgets[provider] = QuotaBudget(max_requests, max_tokens)
        return budgets

    def ensure_available(self, *, provider: str, model: str) -> None:
        budget = self.budgets.get(provider)
        if budget is None:
            raise ProviderError(
                ErrorCode.QUOTA_EXHAUSTED,
                f"No application quota budget is configured for provider '{provider}'.",
                provider=provider,
                model=model,
            )
        now = self.clock()
        start_of_day = now.astimezone(UTC).replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        usage = self.store.model_usage(
            provider=provider,
            model=model,
            since=start_of_day,
        )
        if usage["request_count"] >= budget.max_requests_per_day:
            raise ProviderError(
                ErrorCode.QUOTA_EXHAUSTED,
                f"Application request quota exhausted for {provider}/{model}; retry tomorrow.",
                provider=provider,
                model=model,
            )
        if usage["total_tokens"] >= budget.max_tokens_per_day:
            raise ProviderError(
                ErrorCode.QUOTA_EXHAUSTED,
                f"Application token quota exhausted for {provider}/{model}; retry tomorrow.",
                provider=provider,
                model=model,
            )
