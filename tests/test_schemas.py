from __future__ import annotations

import json
import unittest
from pathlib import Path

import _bootstrap  # noqa: F401
from pydantic import ValidationError

from content_agent.ai.models import (
    CriticResult,
    DraftPost,
    PolicyContext,
    ResearchBrief,
    TokenUsage,
)

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class SchemaTests(unittest.TestCase):
    def test_valid_fixtures(self) -> None:
        self.assertEqual(PolicyContext.model_validate(fixture("policy_valid.json")).threshold, 80)
        self.assertEqual(
            ResearchBrief.model_validate(fixture("research_brief_valid.json")).metadata.provider,
            "gemini",
        )
        self.assertEqual(
            DraftPost.model_validate(fixture("draft_post_valid.json")).metadata.provider,
            "groq",
        )
        self.assertEqual(
            CriticResult.model_validate(fixture("critic_result_valid.json")).decision.value,
            "pass",
        )

    def test_invalid_fixtures_are_rejected(self) -> None:
        cases = [
            (PolicyContext, "policy_invalid.json"),
            (ResearchBrief, "research_brief_invalid.json"),
            (DraftPost, "draft_post_invalid.json"),
            (CriticResult, "critic_result_invalid.json"),
        ]
        for model, name in cases:
            with self.subTest(name=name), self.assertRaises(ValidationError):
                model.model_validate(fixture(name))

    def test_policy_accepts_tai_contract_aliases(self) -> None:
        policy = PolicyContext.from_policy(
            {
                "slug": "account-1",
                "goal": "Educate",
                "constraints": ["Be concise"],
                "examples": [],
                "rubric": {"clarity": 100},
                "threshold": 75,
            }
        )
        self.assertEqual(policy.account_id, "account-1")

    def test_extra_fields_are_rejected(self) -> None:
        value = fixture("policy_valid.json")
        value["unexpected"] = "contract drift"
        with self.assertRaises(ValidationError):
            PolicyContext.model_validate(value)

    def test_usage_total_is_never_lower_than_known_parts(self) -> None:
        usage = TokenUsage(input_tokens=10, output_tokens=5, total_tokens=0)
        self.assertEqual(usage.total_tokens, 15)


if __name__ == "__main__":
    unittest.main()
