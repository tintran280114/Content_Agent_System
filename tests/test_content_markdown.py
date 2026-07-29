from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

import _bootstrap  # noqa: F401
from content_agent.ai.models import ContentMode, ContentSource, ContentTask
from content_agent.content_markdown import (
    GENERATE_TEMPLATE,
    PUBLISH_TEMPLATE,
    ContentMarkdownError,
    import_publish_document,
    parse_content_markdown,
)
from content_agent.critics import render_post
from content_agent.platform import SQLiteRunStore

FIXTURES = Path(__file__).parent / "fixtures"


class ContentMarkdownTests(unittest.TestCase):
    def test_generate_document_maps_to_canonical_content_request(self) -> None:
        document = parse_content_markdown(GENERATE_TEMPLATE, source_name="brief.md")
        request = document.to_content_request()

        self.assertEqual(document.mode, ContentMode.GENERATE)
        self.assertEqual(document.task, ContentTask.CREATE)
        self.assertEqual(document.pipeline, "full")
        self.assertIn("Python", document.topic)
        self.assertIn("checklist", request.instructions)
        self.assertEqual(request.mode, ContentMode.GENERATE)
        self.assertEqual(request.source_type, ContentSource.FILE)
        self.assertEqual(request.source_name, "brief.md")

    def test_publish_document_preserves_extended_markdown_blocks(self) -> None:
        markdown = """---
mode: publish
task: create
pipeline: full
---
# Topic
Release checklist
# Content
> Review before publishing.

1. Check permissions.
2. Check destination.

```python
print("audit")
```

![Diagram](https://example.com/diagram.png)
"""
        document = parse_content_markdown(markdown, source_name="post.markdown")

        self.assertEqual(document.mode, ContentMode.PUBLISH)
        self.assertEqual(
            set(document.block_types),
            {"code_block", "heading", "image", "ordered_list", "quote"},
        )
        self.assertIn("![Diagram]", document.final_content)

    def test_front_matter_rejects_secrets_and_unknown_fields(self) -> None:
        for line in ("access_token: secret", "account_id: hidden-config"):
            with self.subTest(line=line):
                markdown = f"""---
mode: generate
task: create
{line}
---
# Topic
Safe content
"""
                with self.assertRaises(ContentMarkdownError):
                    parse_content_markdown(markdown, source_name="unsafe.md")

    def test_transform_task_requires_source_section(self) -> None:
        markdown = """---
mode: generate
task: summarize
---
# Topic
Weekly recap
# Instructions
Summarize this.
"""
        with self.assertRaisesRegex(ContentMarkdownError, "requires source content"):
            parse_content_markdown(markdown, source_name="missing-source.md")

    def test_publish_import_creates_publishable_run_without_ai(self) -> None:
        document = parse_content_markdown(
            PUBLISH_TEMPLATE.replace("#HocPython #Python", "#ResponsibleAI"),
            source_name="final-post.md",
        )
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteRunStore(Path(directory) / "content.sqlite3")
            result = import_publish_document(
                store,
                policy_path=FIXTURES / "policy_valid.md",
                document=document,
            )

            self.assertEqual(result.workflow_state.value, "passed")
            self.assertTrue(result.hard_rule_passed)
            self.assertEqual(store.get_content_request(result.run_id).mode, ContentMode.PUBLISH)
            draft = store.get_current_draft(result.run_id)
            self.assertEqual(draft.metadata.provider, "operator")
            self.assertEqual(draft.metadata.role, "operator")
            self.assertIn("#ResponsibleAI", render_post(draft))
            self.assertEqual(store.list_review_queue(), [])
            events = store.get_events(result.run_id)
            self.assertFalse(any(event["provider"] in {"gemini", "groq"} for event in events))

    def test_file_validation_is_utf8_markdown_only(self) -> None:
        with self.assertRaises(ContentMarkdownError):
            parse_content_markdown(b"\xff", source_name="bad.md")
        with self.assertRaises(ContentMarkdownError):
            parse_content_markdown(GENERATE_TEMPLATE, source_name="brief.txt")
        with self.assertRaises((ContentMarkdownError, ValidationError)):
            parse_content_markdown(
                GENERATE_TEMPLATE.replace(
                    "Ba cách học Python hiệu quả cho người mới",
                    "x" * 501,
                ),
                source_name="too-long.md",
            )


if __name__ == "__main__":
    unittest.main()
