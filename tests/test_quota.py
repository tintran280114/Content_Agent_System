from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import _bootstrap  # noqa: F401
from content_agent.ai.errors import ErrorCode, ProviderError
from content_agent.ai.models import TokenUsage
from content_agent.platform import EventState, RunStep, SQLiteRunStore
from content_agent.policy import load_policy
from content_agent.quota import QuotaBudget, QuotaManager

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)


class QuotaManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.store = SQLiteRunStore(Path(self.tempdir.name) / "quota.sqlite3")
        self.run_id = uuid4()
        self.store.start_run(
            run_id=self.run_id,
            topic="Responsible AI",
            policy=load_policy(FIXTURES / "policy_valid.md"),
            source_path=FIXTURES / "policy_valid.md",
        )

    def manager(self, *, requests: int = 2, tokens: int = 100) -> QuotaManager:
        return QuotaManager(
            self.store,
            budgets={"gemini": QuotaBudget(requests, tokens)},
            clock=lambda: NOW,
        )

    def test_request_budget_stops_before_overrun(self) -> None:
        self.store.record_event(
            run_id=self.run_id,
            step=RunStep.RESEARCH,
            state=EventState.STARTED,
            provider="gemini",
            model="gemini-test",
        )
        with self.assertRaises(ProviderError) as caught:
            self.manager(requests=1).ensure_available(
                provider="gemini",
                model="gemini-test",
            )
        self.assertEqual(caught.exception.code, ErrorCode.QUOTA_EXHAUSTED)
        self.assertFalse(caught.exception.retryable)

    def test_token_budget_stops_before_next_request(self) -> None:
        self.store.record_event(
            run_id=self.run_id,
            step=RunStep.RESEARCH,
            state=EventState.COMPLETED,
            provider="gemini",
            model="gemini-test",
            usage=TokenUsage(input_tokens=60, output_tokens=40, total_tokens=100),
        )
        with self.assertRaises(ProviderError) as caught:
            self.manager(tokens=100).ensure_available(
                provider="gemini",
                model="gemini-test",
            )
        self.assertEqual(caught.exception.code, ErrorCode.QUOTA_EXHAUSTED)

    def test_usage_summary_has_requests_retries_and_per_run_metrics(self) -> None:
        self.store.record_event(
            run_id=self.run_id,
            step=RunStep.RESEARCH,
            state=EventState.STARTED,
            provider="gemini",
            model="gemini-test",
        )
        self.store.record_event(
            run_id=self.run_id,
            step=RunStep.RESEARCH,
            state=EventState.FAILED,
            provider="gemini",
            model="gemini-test",
            retryable=True,
            error_code="rate_limit",
            error_message="Provider rate limit or quota was reached.",
        )
        self.store.record_event(
            run_id=self.run_id,
            step=RunStep.RESEARCH,
            state=EventState.STARTED,
            provider="gemini",
            model="gemini-test",
            attempt=2,
        )
        self.store.record_event(
            run_id=self.run_id,
            step=RunStep.RESEARCH,
            state=EventState.COMPLETED,
            provider="gemini",
            model="gemini-test",
            attempt=2,
            usage=TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15),
        )

        usage = self.store.usage_summary()

        self.assertEqual(usage["total"]["request_count"], 2)
        self.assertEqual(usage["total"]["retry_count"], 1)
        self.assertEqual(usage["total"]["retry_rate"], 0.5)
        self.assertEqual(usage["by_run"][0]["account_id"], "test-account")
        self.assertEqual(usage["by_run"][0]["total_tokens"], 15)


if __name__ == "__main__":
    unittest.main()
