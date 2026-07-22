from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Literal, Sequence

import _bootstrap  # noqa: F401

from content_agent.ai.agents import CopywriterAgent, ResearchAgent, run_research_copywriter
from content_agent.ai.base import ChatMessage, ProviderResponse, SchemaT, StructuredProvider
from content_agent.ai.models import (
    DraftPayload,
    GenerationMetadata,
    PolicyContext,
    ResearchPayload,
    TokenUsage,
)

FIXTURES = Path(__file__).parent / "fixtures"


class FakeProvider(StructuredProvider):
    def __init__(self, provider_name: str, model: str, payload: dict) -> None:
        self.provider_name = provider_name
        self.model = model
        self.payload = payload
        self.last_messages: Sequence[ChatMessage] = []

    def generate(
        self,
        *,
        messages: Sequence[ChatMessage],
        response_model: type[SchemaT],
        role: Literal["research", "copywriter", "critic"],
        prompt_version: str,
    ) -> ProviderResponse[SchemaT]:
        self.last_messages = messages
        output = response_model.model_validate(self.payload)
        metadata = GenerationMetadata(
            provider=self.provider_name,
            model=self.model,
            role=role,
            prompt_version=prompt_version,
            provider_sdk="fake/1",
            latency_ms=1,
            usage=TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15),
        )
        return ProviderResponse(output=output, metadata=metadata)


class AgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = PolicyContext.model_validate_json(
            (FIXTURES / "policy_valid.json").read_text(encoding="utf-8")
        )
        self.research_payload = {
            "summary": "A sufficiently detailed summary for the shared research contract.",
            "key_points": ["Written policy", "Human review"],
            "audience_insights": ["Small teams value simple workflows"],
            "content_angles": ["Three-step checklist"],
            "risks": ["Unsupported claims"],
            "source_notes": ["No live browsing"],
        }
        self.draft_payload = {
            "content": "Start with written constraints, review each claim, and keep a human accountable.",
            "hashtags": ["#ResponsibleAI"],
            "call_to_action": "What would you review first?",
            "policy_constraints_applied": ["Do not promise guaranteed business results"],
        }

    def test_research_prompt_contains_policy_constraints(self) -> None:
        provider = FakeProvider("gemini", "gemini-test", self.research_payload)
        brief = ResearchAgent(provider).run(topic="Responsible AI", policy=self.policy)
        prompt = "\n".join(message.content for message in provider.last_messages)
        self.assertIn("Do not promise guaranteed business results", prompt)
        self.assertEqual(brief.account_id, self.policy.account_id)
        self.assertEqual(brief.metadata.role, "research")

    def test_copywriter_preserves_traceability(self) -> None:
        research_provider = FakeProvider("gemini", "gemini-test", self.research_payload)
        copy_provider = FakeProvider("groq", "groq-test", self.draft_payload)
        result = run_research_copywriter(
            topic="Responsible AI",
            policy=self.policy,
            research_provider=research_provider,
            copywriter_provider=copy_provider,
        )
        self.assertEqual(result.draft.brief_id, result.research.brief_id)
        self.assertEqual(result.research.metadata.provider, "gemini")
        self.assertEqual(result.draft.metadata.provider, "groq")
        self.assertNotEqual(result.research.metadata.provider, result.draft.metadata.provider)
        copy_prompt = "\n".join(message.content for message in copy_provider.last_messages)
        self.assertIn("Keep the post under 900 characters", copy_prompt)
        self.assertIn("#ResponsibleAI", copy_prompt)
        self.assertIn("revolutionary", copy_prompt)

    def test_copywriter_rejects_policy_account_mismatch(self) -> None:
        research_provider = FakeProvider("gemini", "gemini-test", self.research_payload)
        brief = ResearchAgent(research_provider).run(topic="Responsible AI", policy=self.policy)
        other = self.policy.model_copy(update={"account_id": "other"})
        copy_provider = FakeProvider("groq", "groq-test", self.draft_payload)
        with self.assertRaisesRegex(ValueError, "account_id"):
            CopywriterAgent(copy_provider).run(research=brief, policy=other)


if __name__ == "__main__":
    unittest.main()
