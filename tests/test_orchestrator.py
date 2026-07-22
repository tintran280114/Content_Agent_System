from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Literal, Sequence

import _bootstrap  # noqa: F401

from content_agent.ai.base import ChatMessage, ProviderResponse, SchemaT, StructuredProvider
from content_agent.ai.config import Role
from content_agent.ai.errors import ErrorCode, ProviderError
from content_agent.ai.models import GenerationMetadata, TokenUsage
from content_agent.orchestrator import Day1Orchestrator, Day1RunError
from content_agent.platform import SQLiteRunStore

FIXTURES = Path(__file__).parent / "fixtures"


class FakeProvider(StructuredProvider):
    def __init__(self, provider_name: str, model: str, payload: dict) -> None:
        self.provider_name = provider_name
        self.model = model
        self.payload = payload

    def generate(
        self,
        *,
        messages: Sequence[ChatMessage],
        response_model: type[SchemaT],
        role: Literal["research", "copywriter", "critic"],
        prompt_version: str,
    ) -> ProviderResponse[SchemaT]:
        output = response_model.model_validate(self.payload)
        metadata = GenerationMetadata(
            provider=self.provider_name,
            model=self.model,
            role=role,
            prompt_version=prompt_version,
            provider_sdk="fake/1",
            latency_ms=2,
            usage=TokenUsage(input_tokens=12, output_tokens=8, total_tokens=20),
        )
        return ProviderResponse(output=output, metadata=metadata)


class FailingProvider(StructuredProvider):
    provider_name = "gemini"
    model = "gemini-test"

    def generate(self, **kwargs):
        raise ProviderError(
            ErrorCode.RATE_LIMIT,
            "Provider rate limit or quota was reached.",
            provider=self.provider_name,
            model=self.model,
            retryable=True,
            status_code=429,
        )


class OrchestratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.store = SQLiteRunStore(Path(self.tempdir.name) / "runs.sqlite3")
        self.research_payload = {
            "summary": "A detailed research summary grounded in the supplied policy and topic.",
            "key_points": ["Use written constraints", "Keep human accountability"],
            "audience_insights": ["Small teams need simple review workflows"],
            "content_angles": ["A concise three-step checklist"],
            "risks": ["Unsupported claims"],
            "source_notes": ["No live browsing was performed"],
        }
        self.draft_payload = {
            "content": "Write the policy first, review every claim, and keep a person accountable.",
            "hashtags": ["#ResponsibleAI"],
            "call_to_action": "Which review step would your team add?",
            "policy_constraints_applied": ["Do not promise guaranteed results"],
        }

    def test_vertical_slice_persists_every_contract_under_one_run_id(self) -> None:
        providers = {
            Role.RESEARCH: FakeProvider("gemini", "gemini-test", self.research_payload),
            Role.COPYWRITER: FakeProvider("groq", "groq-test", self.draft_payload),
        }
        result = Day1Orchestrator(
            self.store,
            provider_factory=lambda role: providers[role],
        ).run(topic="Responsible AI", policy_path=FIXTURES / "policy_valid.md")

        run = self.store.get_run(result.run_id)
        self.assertIsNotNone(run)
        self.assertEqual(run["state"], "completed")
        self.assertEqual(run["account_id"], result.policy.account_id)
        self.assertEqual(result.draft.brief_id, result.research.brief_id)

        artifacts = self.store.get_artifacts(result.run_id)
        self.assertEqual(
            set(artifacts),
            {"account_policy", "research_brief", "draft_post"},
        )
        self.assertEqual(
            artifacts["draft_post"]["payload"]["brief_id"],
            artifacts["research_brief"]["entity_id"],
        )

        events = self.store.get_events(result.run_id)
        self.assertEqual(events[0]["step"], "run")
        self.assertEqual(events[-1]["state"], "completed")
        self.assertEqual(
            {(event["step"], event["provider"]) for event in events if event["provider"]},
            {("research", "gemini"), ("copywriter", "groq")},
        )
        self.assertEqual(sum(event["total_tokens"] for event in events), 40)

    def test_provider_failure_is_safe_and_traceable(self) -> None:
        with self.assertRaises(Day1RunError) as caught:
            Day1Orchestrator(
                self.store,
                provider_factory=lambda role: FailingProvider(),
            ).run(topic="Responsible AI", policy_path=FIXTURES / "policy_valid.md")

        error = caught.exception
        self.assertEqual(error.code, "rate_limit")
        run = self.store.get_run(error.run_id)
        self.assertEqual(run["state"], "failed")
        self.assertEqual(run["error_code"], "rate_limit")
        events = self.store.get_events(error.run_id)
        failed = [event for event in events if event["state"] == "failed"]
        self.assertTrue(failed)
        self.assertTrue(any(event["retryable"] == 1 for event in failed))
        self.assertNotIn("secret", str(events).casefold())

    def test_policy_route_mismatch_fails_before_provider_call(self) -> None:
        policy_text = (FIXTURES / "policy_valid.md").read_text(encoding="utf-8")
        policy_text = policy_text.replace("- research: gemini", "- research: groq")
        policy_path = Path(self.tempdir.name) / "route-mismatch.md"
        policy_path.write_text(policy_text, encoding="utf-8")
        providers = {
            Role.RESEARCH: FakeProvider("gemini", "gemini-test", self.research_payload),
            Role.COPYWRITER: FakeProvider("groq", "groq-test", self.draft_payload),
        }

        with self.assertRaises(Day1RunError) as caught:
            Day1Orchestrator(
                self.store,
                provider_factory=lambda role: providers[role],
            ).run(topic="Responsible AI", policy_path=policy_path)

        error = caught.exception
        self.assertEqual(error.code, "contract_mismatch")
        self.assertIn("runtime selected 'gemini'", str(error))
        run = self.store.get_run(error.run_id)
        self.assertEqual(run["state"], "failed")


if __name__ == "__main__":
    unittest.main()
