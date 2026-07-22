from __future__ import annotations

import unittest
from pathlib import Path

import _bootstrap  # noqa: F401

from content_agent.ai.models import PolicyContext
from content_agent.policy import PolicyParseError, load_policies, load_policy, parse_policy_text

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"


class PolicyTests(unittest.TestCase):
    def test_three_differentiated_account_policies_parse(self) -> None:
        paths = sorted(
            path for path in (ROOT / "accounts").glob("*.md") if path.name != "template.md"
        )
        policies = load_policies(paths)
        self.assertEqual(len(policies), 3)
        self.assertEqual(len({policy.account_id for policy in policies}), 3)
        self.assertEqual(len({policy.platform for policy in policies}), 3)
        self.assertEqual(len({policy.max_length for policy in policies}), 3)

    def test_policy_is_compatible_with_ai_handoff(self) -> None:
        policy = load_policy(FIXTURES / "policy_valid.md")
        context = PolicyContext.from_policy(policy)
        self.assertEqual(context.account_id, policy.account_id)
        self.assertEqual(context.constraints, policy.constraints)
        self.assertEqual(context.max_length, policy.max_length)

    def test_missing_section_error_names_file_and_section(self) -> None:
        path = FIXTURES / "policy_invalid.md"
        with self.assertRaises(PolicyParseError) as caught:
            load_policy(path)
        message = str(caught.exception)
        self.assertIn(str(path), message)
        self.assertIn("## Rubric", message)

    def test_invalid_rubric_is_actionable(self) -> None:
        text = (FIXTURES / "policy_valid.md").read_text(encoding="utf-8")
        text = text.replace("- originality: 10", "- originality: 9")
        with self.assertRaises(PolicyParseError) as caught:
            parse_policy_text(text, source="bad-rubric.md")
        self.assertIn("Rubric", str(caught.exception))
        self.assertIn("total 100", str(caught.exception))

    def test_copywriter_and_critic_provider_separation_is_enforced(self) -> None:
        text = (FIXTURES / "policy_valid.md").read_text(encoding="utf-8")
        text = text.replace("- critic: github_models", "- critic: groq")
        with self.assertRaises(PolicyParseError) as caught:
            parse_policy_text(text, source="same-provider.md")
        self.assertIn("Model Route", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
