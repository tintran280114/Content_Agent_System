from __future__ import annotations

import tempfile
import unittest
from collections.abc import Sequence
from pathlib import Path
from typing import Literal
from uuid import uuid4

import _bootstrap  # noqa: F401
from content_agent.ai.base import ChatMessage, ProviderResponse, SchemaT, StructuredProvider
from content_agent.ai.config import Role
from content_agent.ai.errors import ErrorCode, ProviderError
from content_agent.ai.models import GenerationMetadata, TokenUsage
from content_agent.orchestrator import PipelineOrchestrator, PipelineRunError
from content_agent.platform import EventState, RunStep, SQLiteRunStore
from content_agent.policy import load_policy
from content_agent.publisher import MockPublisher, Publisher
from content_agent.quota import QuotaBudget, QuotaManager
from content_agent.review import ReviewService
from content_agent.workflow import PublishStatus, WorkflowState

FIXTURES = Path(__file__).parent / "fixtures"


class SequenceProvider(StructuredProvider):
    def __init__(self, provider_name: str, model: str, responses: list[dict | Exception]) -> None:
        self.provider_name = provider_name
        self.model = model
        self.responses = list(responses)
        self.calls = 0

    def generate(
        self,
        *,
        messages: Sequence[ChatMessage],
        response_model: type[SchemaT],
        role: Literal["research", "copywriter", "critic"],
        prompt_version: str,
    ) -> ProviderResponse[SchemaT]:
        self.calls += 1
        if not self.responses:
            raise AssertionError(f"No fake response left for {self.provider_name}")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return ProviderResponse(
            output=response_model.model_validate(response),
            metadata=GenerationMetadata(
                provider=self.provider_name,
                model=self.model,
                role=role,
                prompt_version=prompt_version,
                provider_sdk="fake/1",
                latency_ms=1,
                usage=TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15),
            ),
        )


RESEARCH = {
    "summary": "A detailed research summary grounded in the supplied account policy.",
    "key_points": ["Use written constraints", "Keep a human accountable"],
    "audience_insights": ["Small teams need a reviewable workflow"],
    "content_angles": ["A concise safety checklist"],
    "risks": ["Unsupported claims"],
    "source_notes": ["No live browsing was performed"],
}
DRAFT = {
    "content": "Write a policy, review every claim, and keep a human accountable.",
    "hashtags": ["#ResponsibleAI"],
    "call_to_action": "What would your team review first?",
    "policy_constraints_applied": ["Keep a human responsible for publication"],
}
REWRITE = {
    "content": "Start with written rules, check each claim, and keep final responsibility with a person.",
    "hashtags": ["#ResponsibleAI"],
    "call_to_action": "Which check will you add?",
    "policy_constraints_applied": ["Do not promise guaranteed results"],
}
PASS = {
    "rule_passed": True,
    "score": 92,
    "violations": [],
    "suggestions": ["Keep the concrete checklist."],
    "decision": "pass",
}
FAIL = {
    "rule_passed": True,
    "score": 60,
    "violations": ["The explanation needs a clearer practical step."],
    "suggestions": ["Add one specific review action."],
    "decision": "rewrite",
}


class FullPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.store = SQLiteRunStore(Path(self.tempdir.name) / "pipeline.sqlite3")

    def orchestrator(
        self,
        *,
        drafts: list[dict],
        critics: list[dict | Exception],
        research_responses: list[dict | Exception] | None = None,
        sleep_calls: list[float] | None = None,
        quota_manager: QuotaManager | None = None,
    ) -> tuple[PipelineOrchestrator, dict[Role, SequenceProvider]]:
        providers = {
            Role.RESEARCH: SequenceProvider("gemini", "gemini-test", research_responses or [RESEARCH]),
            Role.COPYWRITER: SequenceProvider("groq", "groq-test", drafts),
            Role.CRITIC: SequenceProvider("github_models", "github-test", critics),
        }
        orchestrator = PipelineOrchestrator(
            self.store,
            provider_factory=lambda role, **_: providers[role],
            base_backoff_seconds=0.25,
            sleeper=(sleep_calls.append if sleep_calls is not None else lambda _: None),
            quota_manager=quota_manager,
        )
        return orchestrator, providers

    def test_pass_path_mock_publishes(self) -> None:
        orchestrator, _ = self.orchestrator(drafts=[DRAFT], critics=[PASS])
        result = orchestrator.run(topic="Responsible AI", policy_path=FIXTURES / "policy_valid.md")
        self.assertEqual(result.workflow_state, WorkflowState.PUBLISHED)
        self.assertEqual(result.rewrite_count, 0)
        self.assertEqual(result.publish_receipt.status, PublishStatus.PUBLISHED)
        self.assertEqual(self.store.get_workflow(result.run_id)["state"], "published")
        self.assertEqual(len(self.store.get_publish_attempts(result.run_id)), 1)

    def test_policy_can_require_human_approval_before_any_publish_attempt(self) -> None:
        text = (FIXTURES / "policy_valid.md").read_text(encoding="utf-8")
        text += """

## Publishing
- adapter: mock
- approval_required: true
"""
        policy_path = Path(self.tempdir.name) / "approval-required.md"
        policy_path.write_text(text, encoding="utf-8")
        orchestrator, _ = self.orchestrator(drafts=[DRAFT], critics=[PASS])

        result = orchestrator.run(topic="Responsible AI", policy_path=policy_path)

        self.assertEqual(result.workflow_state, WorkflowState.HUMAN_REVIEW)
        self.assertEqual(self.store.get_publish_attempts(result.run_id), [])

    def test_fail_then_rewrite_then_pass(self) -> None:
        orchestrator, providers = self.orchestrator(
            drafts=[DRAFT, REWRITE],
            critics=[FAIL, PASS],
        )
        result = orchestrator.run(topic="Responsible AI", policy_path=FIXTURES / "policy_valid.md")
        self.assertEqual(result.workflow_state, WorkflowState.PUBLISHED)
        self.assertEqual(result.rewrite_count, 1)
        self.assertEqual(providers[Role.COPYWRITER].calls, 2)
        self.assertEqual(len(self.store.score_history()), 2)

    def test_fail_after_two_rewrites_enters_human_review_and_guard_blocks(self) -> None:
        orchestrator, providers = self.orchestrator(
            drafts=[DRAFT, REWRITE, REWRITE],
            critics=[FAIL, FAIL, FAIL],
        )
        result = orchestrator.run(topic="Responsible AI", policy_path=FIXTURES / "policy_valid.md")
        self.assertEqual(result.workflow_state, WorkflowState.HUMAN_REVIEW)
        self.assertEqual(result.rewrite_count, 2)
        self.assertEqual(providers[Role.COPYWRITER].calls, 3)
        receipt = MockPublisher(self.store).publish(result.run_id)
        self.assertEqual(receipt.status, PublishStatus.BLOCKED)
        self.assertEqual(self.store.get_workflow(result.run_id)["state"], "human_review")

    def test_retryable_provider_error_retries_with_backoff(self) -> None:
        sleep_calls: list[float] = []
        error = ProviderError(
            ErrorCode.RATE_LIMIT,
            "Provider rate limit or quota was reached.",
            provider="gemini",
            model="gemini-test",
            retryable=True,
            status_code=429,
        )
        orchestrator, providers = self.orchestrator(
            drafts=[DRAFT],
            critics=[PASS],
            research_responses=[error, RESEARCH],
            sleep_calls=sleep_calls,
        )
        result = orchestrator.run(topic="Responsible AI", policy_path=FIXTURES / "policy_valid.md")
        self.assertEqual(result.workflow_state, WorkflowState.PUBLISHED)
        self.assertEqual(providers[Role.RESEARCH].calls, 2)
        self.assertEqual(sleep_calls, [0.25])
        failed = [event for event in self.store.get_events(result.run_id) if event["error_code"]]
        self.assertEqual(failed[0]["error_code"], "rate_limit")
        self.assertEqual(failed[0]["retryable"], 1)

    def test_application_quota_stops_before_a_second_provider_request(self) -> None:
        error = ProviderError(
            ErrorCode.RATE_LIMIT,
            "Provider rate limit or quota was reached.",
            provider="gemini",
            model="gemini-test",
            retryable=True,
            status_code=429,
        )
        budgets = {
            "gemini": QuotaBudget(1, 100_000),
            "groq": QuotaBudget(10, 100_000),
            "github_models": QuotaBudget(10, 100_000),
        }
        orchestrator, providers = self.orchestrator(
            drafts=[DRAFT],
            critics=[PASS],
            research_responses=[error, RESEARCH],
            quota_manager=QuotaManager(self.store, budgets=budgets),
        )

        with self.assertRaises(PipelineRunError) as caught:
            orchestrator.run(topic="Responsible AI", policy_path=FIXTURES / "policy_valid.md")

        self.assertEqual(caught.exception.code, "quota_exhausted")
        self.assertEqual(providers[Role.RESEARCH].calls, 1)
        events = self.store.get_events(caught.exception.run_id)
        self.assertEqual(
            sum(event["state"] == "started" and event["provider"] == "gemini" for event in events),
            1,
        )

    def test_quota_exhaustion_after_a_draft_stops_batch_safely(self) -> None:
        prior_run = uuid4()
        self.store.start_run(
            run_id=prior_run,
            topic="Prior usage",
            policy=load_policy(FIXTURES / "policy_valid.md"),
            source_path=FIXTURES / "policy_valid.md",
        )
        self.store.record_event(
            run_id=prior_run,
            step=RunStep.LLM_CRITIC,
            state=EventState.STARTED,
            provider="github_models",
            model="github-test",
        )
        self.store.complete_run(prior_run)
        budgets = {
            "gemini": QuotaBudget(10, 100_000),
            "groq": QuotaBudget(10, 100_000),
            "github_models": QuotaBudget(1, 100_000),
        }
        orchestrator, providers = self.orchestrator(
            drafts=[DRAFT],
            critics=[PASS],
            quota_manager=QuotaManager(self.store, budgets=budgets),
        )

        result = orchestrator.run(
            topic="Responsible AI",
            policy_path=FIXTURES / "policy_valid.md",
        )

        self.assertEqual(result.workflow_state, WorkflowState.HUMAN_REVIEW)
        self.assertEqual(result.terminal_error_code, "quota_exhausted")
        self.assertEqual(providers[Role.CRITIC].calls, 0)

    def test_critic_provider_failure_routes_existing_draft_to_human_review(self) -> None:
        error = ProviderError(
            ErrorCode.MISSING_CREDENTIAL,
            "Missing credential: set GITHUB_MODELS_TOKEN before calling github_models.",
            provider="github_models",
            model="github-test",
        )
        orchestrator, _ = self.orchestrator(drafts=[DRAFT], critics=[error])
        result = orchestrator.run(topic="Responsible AI", policy_path=FIXTURES / "policy_valid.md")
        self.assertEqual(result.workflow_state, WorkflowState.HUMAN_REVIEW)
        workflow = self.store.get_workflow(result.run_id)
        self.assertEqual(workflow["last_error_code"], "missing_credential")
        self.assertEqual(self.store.get_publish_attempts(result.run_id), [])

    def test_missing_research_credential_is_a_traceable_failed_run(self) -> None:
        error = ProviderError(
            ErrorCode.MISSING_CREDENTIAL,
            "Missing credential: set GEMINI_API_KEY before calling gemini.",
            provider="gemini",
            model="gemini-test",
        )

        def factory(role: Role, **_):
            if role == Role.RESEARCH:
                raise error
            raise AssertionError("No later provider should be created")

        orchestrator = PipelineOrchestrator(self.store, provider_factory=factory)
        with self.assertRaises(PipelineRunError) as caught:
            orchestrator.run(topic="Responsible AI", policy_path=FIXTURES / "policy_valid.md")
        run = self.store.get_run(caught.exception.run_id)
        self.assertEqual(run["state"], "failed")
        research_failures = [
            event
            for event in self.store.get_events(caught.exception.run_id)
            if event["step"] == "research" and event["state"] == "failed"
        ]
        self.assertEqual(research_failures[0]["error_code"], "missing_credential")

    def test_review_edit_and_approve_are_audited(self) -> None:
        orchestrator, _ = self.orchestrator(
            drafts=[DRAFT, REWRITE, REWRITE],
            critics=[FAIL, FAIL, FAIL],
        )
        result = orchestrator.run(topic="Responsible AI", policy_path=FIXTURES / "policy_valid.md")
        service = ReviewService(self.store)
        edited = service.edit(
            result.run_id,
            actor="operator@example.com",
            content="A human-edited post with explicit accountability.",
            note="Clarified ownership.",
        )
        self.assertEqual(self.store.get_current_draft(result.run_id).draft_id, edited.draft_id)
        receipt = service.approve(
            result.run_id,
            actor="operator@example.com",
            note="Human reviewed every claim.",
        )
        self.assertEqual(receipt.status, PublishStatus.PUBLISHED)
        self.assertEqual(self.store.get_workflow(result.run_id)["state"], "published")
        self.assertEqual(
            [action["action"] for action in self.store.get_review_actions(result.run_id)],
            ["edit", "approve"],
        )

    def test_human_approval_cannot_override_hard_policy_violations(self) -> None:
        orchestrator, _ = self.orchestrator(
            drafts=[DRAFT, REWRITE, REWRITE],
            critics=[FAIL, FAIL, FAIL],
        )
        result = orchestrator.run(topic="Responsible AI", policy_path=FIXTURES / "policy_valid.md")
        service = ReviewService(self.store)
        service.edit(
            result.run_id,
            actor="operator@example.com",
            content="This offers guaranteed results while removing human accountability.",
            note="Testing the final publication guard.",
        )

        with self.assertRaisesRegex(ValueError, "BANNED_TERM"):
            service.approve(
                result.run_id,
                actor="operator@example.com",
                note="Attempting an unsafe override.",
            )

        self.assertEqual(self.store.get_workflow(result.run_id)["state"], "human_review")
        self.assertEqual(self.store.get_publish_attempts(result.run_id), [])
        self.assertEqual(
            [action["action"] for action in self.store.get_review_actions(result.run_id)],
            ["edit"],
        )

    def test_rejected_review_item_never_publishes(self) -> None:
        orchestrator, _ = self.orchestrator(
            drafts=[DRAFT, REWRITE, REWRITE],
            critics=[FAIL, FAIL, FAIL],
        )
        result = orchestrator.run(topic="Responsible AI", policy_path=FIXTURES / "policy_valid.md")
        ReviewService(self.store).reject(
            result.run_id,
            actor="operator@example.com",
            note="Claims need source verification.",
        )
        receipt = MockPublisher(self.store).publish(result.run_id)
        self.assertEqual(receipt.status, PublishStatus.BLOCKED)
        self.assertEqual(self.store.get_workflow(result.run_id)["state"], "rejected")

    def test_mock_publisher_satisfies_swappable_publisher_contract(self) -> None:
        self.assertIsInstance(MockPublisher(self.store), Publisher)


if __name__ == "__main__":
    unittest.main()
