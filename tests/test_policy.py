from __future__ import annotations

import unittest
from pathlib import Path

import _bootstrap  # noqa: F401
from content_agent.ai.models import PolicyContext
from content_agent.policy import PolicyParseError, load_policies, load_policy, parse_policy_text

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"


class PolicyTests(unittest.TestCase):
    def test_differentiated_account_policies_parse(self) -> None:
        paths = sorted(path for path in (ROOT / "accounts").glob("*.md") if path.name != "template.md")
        policies = load_policies(paths)
        self.assertEqual(len(policies), 4)
        self.assertEqual(len({policy.account_id for policy in policies}), 4)
        self.assertEqual(len({policy.platform for policy in policies}), 4)
        self.assertEqual(len({policy.max_length for policy in policies}), 4)

    def test_linkedin_policy_routes_to_a_non_secret_member_target(self) -> None:
        policy = load_policy(ROOT / "accounts" / "linkedin-professional.md")
        self.assertEqual(policy.publishing.adapter, "linkedin")
        self.assertTrue(policy.publishing.target_id.startswith("urn:li:person:"))
        self.assertEqual(
            policy.publishing.credential_ref,
            "LINKEDIN_EXAMPLE_ACCESS_TOKEN",
        )

    def test_policy_is_compatible_with_ai_handoff(self) -> None:
        policy = load_policy(FIXTURES / "policy_valid.md")
        context = PolicyContext.from_policy(policy)
        self.assertEqual(context.account_id, policy.account_id)
        self.assertEqual(context.constraints, policy.constraints)
        self.assertEqual(context.max_length, policy.max_length)

    def test_v02_policy_controls_model_and_non_secret_publisher_route(self) -> None:
        policy = load_policy(ROOT / "accounts" / "community-learning.md")
        self.assertEqual(policy.spec_version, "0.2")
        self.assertTrue(policy.active)
        self.assertEqual(policy.model_route["research"], "gemini")
        self.assertEqual(
            policy.model_overrides["copywriter"],
            "openai/gpt-oss-120b",
        )
        self.assertEqual(policy.publishing.adapter, "facebook_page")
        self.assertEqual(
            policy.publishing.credential_ref,
            "FACEBOOK_COMMUNITY_PAGE_TOKEN",
        )

    def test_threads_topic_tags_are_normalized_and_trend_search_is_configured(self) -> None:
        policy = load_policy(ROOT / "accounts" / "responsible-ai-lab.md")
        self.assertEqual(policy.publishing.adapter, "threads")
        self.assertEqual(policy.publishing.topic_tag, "Responsible AI")
        self.assertEqual(
            policy.publishing.topic_tag_candidates,
            ["Responsible AI", "AI Tools", "AI for Business"],
        )
        self.assertTrue(policy.publishing.trend_search)

    def test_facebook_policy_rejects_threads_topic_settings(self) -> None:
        text = (ROOT / "accounts" / "community-learning.md").read_text(encoding="utf-8")
        text = text.replace(
            "- approval_required: true",
            "- topic_tag: AI Tools\n- approval_required: true",
        )
        with self.assertRaises(PolicyParseError) as caught:
            parse_policy_text(text, source="facebook-with-topic-tag.md")
        self.assertIn("Publishing", str(caught.exception))

    def test_threads_policy_caps_total_topic_searches_at_five(self) -> None:
        text = (ROOT / "accounts" / "responsible-ai-lab.md").read_text(encoding="utf-8")
        text = text.replace(
            "- topic_tag_candidates: Responsible AI | AI Tools | AI for Business",
            "- topic_tag_candidates: AI Tools | AI Business | AI News | AI Safety | AI Agents",
        )
        with self.assertRaises(PolicyParseError) as caught:
            parse_policy_text(text, source="too-many-topic-tags.md")
        self.assertIn("at most five", str(caught.exception))

    def test_real_publisher_requires_a_secret_reference_not_a_literal_token(self) -> None:
        text = (ROOT / "accounts" / "template.md").read_text(encoding="utf-8")
        text = text.replace("- adapter: mock", "- adapter: facebook_page")
        text = text.replace(
            "- approval_required: true",
            "- target_id: 123456\n- credential_ref: gsk_literal_secret_value\n- approval_required: true",
        )
        with self.assertRaises(PolicyParseError) as caught:
            parse_policy_text(text, source="literal-token.md")
        self.assertIn("Publishing", str(caught.exception))

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

    def test_copywriter_and_critic_can_share_a_provider(self) -> None:
        text = (FIXTURES / "policy_valid.md").read_text(encoding="utf-8")
        text = text.replace("- critic: github_models", "- critic: groq")
        policy = parse_policy_text(text, source="same-provider.md")
        self.assertEqual(policy.model_route["copywriter"], "groq")
        self.assertEqual(policy.model_route["critic"], "groq")


if __name__ == "__main__":
    unittest.main()
