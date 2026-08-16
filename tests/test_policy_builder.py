from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import _bootstrap  # noqa: F401
from content_agent.policy import parse_policy_text
from content_agent.policy_builder import (
    PolicyBuilderInput,
    render_policy_markdown,
    save_policy_markdown,
    split_lines,
)


def builder_values(**updates) -> PolicyBuilderInput:
    values = {
        "display_name": "Vietnam AI Studio",
        "account_id": "vietnam-ai-studio",
        "goal": "Teach small teams to create useful and responsible social content.",
        "audience": "Vietnamese founders and content operators.",
        "platform": "Threads",
        "tone": "Practical, friendly, and trustworthy.",
        "language": "Vietnamese",
        "constraints": ["Do not promise guaranteed results.", "Use concrete examples."],
        "banned_terms": ["guaranteed"],
        "required_hashtags": ["ResponsibleAI"],
        "examples": [
            "Bắt đầu nhỏ, đo lường kết quả và luôn có người chịu trách nhiệm.",
            "Mỗi bản nháp AI vẫn cần bằng chứng và một người kiểm duyệt.",
        ],
        "adapter": "mock",
        "approval_required": True,
    }
    values.update(updates)
    return PolicyBuilderInput(**values)


class PolicyBuilderTests(unittest.TestCase):
    def test_guided_form_renders_a_canonical_parseable_policy(self) -> None:
        markdown = render_policy_markdown(builder_values())
        policy = parse_policy_text(markdown, source="generated.md")

        self.assertEqual(policy.account_id, "vietnam-ai-studio")
        self.assertEqual(policy.platform, "Threads")
        self.assertEqual(policy.required_hashtags, ["#ResponsibleAI"])
        self.assertEqual(policy.model_route["research"], "gemini")
        self.assertEqual(policy.model_route["copywriter"], "groq")
        self.assertEqual(policy.model_route["critic"], "groq")
        self.assertEqual(policy.model_overrides["critic"], "openai/gpt-oss-20b")
        self.assertTrue(policy.publishing.approval_required)

    def test_threads_builder_includes_topic_selection_and_secret_reference(self) -> None:
        markdown = render_policy_markdown(
            builder_values(
                adapter="threads",
                target_id="123456789",
                credential_ref="THREADS_VIETNAM_AI_TOKEN",
                topic_tag="Responsible AI",
                topic_tag_candidates=["Responsible AI", "AI Tools"],
                trend_search=True,
            )
        )
        policy = parse_policy_text(markdown, source="threads-generated.md")

        self.assertEqual(policy.publishing.adapter, "threads")
        self.assertEqual(
            policy.publishing.topic_tag_candidates,
            ["Responsible AI", "AI Tools"],
        )
        self.assertEqual(
            policy.publishing.credential_ref,
            "THREADS_VIETNAM_AI_TOKEN",
        )

    def test_linkedin_builder_renders_a_personal_publisher_route(self) -> None:
        markdown = render_policy_markdown(
            builder_values(
                platform="LinkedIn",
                adapter="linkedin",
                target_id="urn:li:person:123456789",
                credential_ref="LINKEDIN_VIETNAM_AI_TOKEN",
            )
        )
        policy = parse_policy_text(markdown, source="linkedin-generated.md")
        self.assertEqual(policy.publishing.adapter, "linkedin")
        self.assertEqual(policy.publishing.target_id, "urn:li:person:123456789")

    def test_builder_saves_atomically_and_requires_explicit_overwrite(self) -> None:
        markdown = render_policy_markdown(builder_values())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path, policy = save_policy_markdown(markdown, root)
            self.assertEqual(path.name, "vietnam-ai-studio.md")
            self.assertEqual(policy.account_id, "vietnam-ai-studio")
            self.assertEqual(path.read_text(encoding="utf-8"), markdown)

            with self.assertRaises(FileExistsError):
                save_policy_markdown(markdown, root)

            replaced, _ = save_policy_markdown(markdown, root, overwrite=True)
            self.assertEqual(replaced, path)

    def test_split_lines_accepts_plain_text_or_markdown_bullets(self) -> None:
        self.assertEqual(
            split_lines(" first item\n- second item\n\n"),
            ["first item", "second item"],
        )

    def test_builder_rejects_a_rubric_that_does_not_total_100(self) -> None:
        with self.assertRaisesRegex(ValueError, "must total 100"):
            builder_values(originality_weight=9)


if __name__ == "__main__":
    unittest.main()
