from __future__ import annotations

import unittest

from pydantic import ValidationError

import _bootstrap  # noqa: F401
from content_agent.ai.models import ContentRequest, ContentSource, ContentTask


class ContentRequestTests(unittest.TestCase):
    def test_topic_instructions_and_source_are_independent(self) -> None:
        request = ContentRequest.from_inputs(
            topic="New offline feature",
            instructions="Use a calm tone and end with a product trial CTA.",
            source_content="Release note: offline mode launches on Monday for all free users.",
            source_name="release.md",
            task=ContentTask.REPURPOSE,
        )

        self.assertEqual(request.topic, "New offline feature")
        self.assertIn("product trial", request.instructions)
        self.assertIn("offline mode", request.source_content)
        self.assertEqual(request.source_type, ContentSource.FILE)
        self.assertEqual(request.task, ContentTask.REPURPOSE)

    def test_pasted_content_is_identified_without_a_file_name(self) -> None:
        request = ContentRequest.from_inputs(
            topic="Weekly recap",
            source_content="Three customer interviews highlighted simpler onboarding.",
        )

        self.assertEqual(request.source_type, ContentSource.PASTED)
        self.assertIsNone(request.source_name)

    def test_create_from_topic_does_not_require_source_content(self) -> None:
        request = ContentRequest.from_inputs(topic="Responsible AI")

        self.assertEqual(request.task, ContentTask.CREATE)
        self.assertEqual(request.source_type, ContentSource.NONE)
        self.assertFalse(request.has_source_content)

    def test_transform_tasks_require_source_content(self) -> None:
        for task in (ContentTask.REPURPOSE, ContentTask.REWRITE, ContentTask.SUMMARIZE):
            with self.subTest(task=task):
                with self.assertRaisesRegex(ValidationError, "requires source content"):
                    ContentRequest.from_inputs(topic="Launch", task=task)

    def test_source_content_has_a_free_tier_safe_size_limit(self) -> None:
        with self.assertRaisesRegex(ValidationError, "at most 30000"):
            ContentRequest.from_inputs(topic="Long source", source_content="x" * 30_001)


if __name__ == "__main__":
    unittest.main()
