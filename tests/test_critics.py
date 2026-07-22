from __future__ import annotations

import json
import unittest
from pathlib import Path

import _bootstrap  # noqa: F401

from content_agent.ai.models import DraftPost
from content_agent.critics import RuleCritic, ViolationCode, render_post
from content_agent.policy import load_policy

FIXTURES = Path(__file__).parent / "fixtures"


class RuleCriticTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = load_policy(FIXTURES / "policy_valid.md")
        payload = json.loads((FIXTURES / "draft_post_valid.json").read_text(encoding="utf-8"))
        payload["account_id"] = "test-account"
        self.draft = DraftPost.model_validate(payload)

    def test_valid_draft_passes_and_renders_publishable_fields(self) -> None:
        result = RuleCritic().evaluate(draft=self.draft, policy=self.policy)
        self.assertTrue(result.passed)
        self.assertIn(self.draft.call_to_action, render_post(self.draft))
        self.assertIn("#ResponsibleAI", render_post(self.draft))

    def test_hard_violations_have_stable_codes(self) -> None:
        bad = self.draft.model_copy(
            update={
                "content": "Guaranteed " + ("x" * 900),
                "hashtags": ["bad hashtag"],
            }
        )
        result = RuleCritic().evaluate(draft=bad, policy=self.policy)
        codes = {violation.code for violation in result.violations}
        self.assertIn(ViolationCode.MAX_LENGTH, codes)
        self.assertIn(ViolationCode.BANNED_TERM, codes)
        self.assertIn(ViolationCode.REQUIRED_HASHTAG, codes)
        self.assertIn(ViolationCode.INVALID_HASHTAG, codes)

    def test_constraint_metadata_does_not_trigger_banned_term(self) -> None:
        draft = self.draft.model_copy(
            update={
                "content": "A careful workflow keeps people accountable.",
                "policy_constraints_applied": ["Do not promise guaranteed results"],
            }
        )
        result = RuleCritic().evaluate(draft=draft, policy=self.policy)
        self.assertFalse(any(v.code == ViolationCode.BANNED_TERM for v in result.violations))


if __name__ == "__main__":
    unittest.main()
