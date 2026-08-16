from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from streamlit.testing.v1 import AppTest

import _bootstrap  # noqa: F401
from content_agent.ai.models import CriticResult, Decision, DraftPost, ResearchBrief
from content_agent.critics import RuleCritic
from content_agent.platform import SQLiteRunStore
from content_agent.policy import load_policy
from content_agent.workflow import DraftOrigin

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"


class StreamlitAppTests(unittest.TestCase):
    def test_post_preview_copy_is_selected_from_the_platform(self) -> None:
        source = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
        self.assertIn('casefold() == "linkedin"', source)
        self.assertIn("LinkedIn personal post preview", source)
        self.assertIn("_post_preview_heading(publish_policy.platform)", source)

    def test_empty_database_dashboard_renders_without_exception(self) -> None:
        previous = os.environ.get("CONTENT_AGENT_DB")
        try:
            with tempfile.TemporaryDirectory() as directory:
                os.environ["CONTENT_AGENT_DB"] = str(Path(directory) / "dashboard.sqlite3")
                app = AppTest.from_file(
                    str(ROOT / "streamlit_app.py"),
                    default_timeout=15,
                ).run()
                self.assertEqual(list(app.exception), [])
                self.assertEqual(app.title[0].value, "Content Operations")
                self.assertFalse(any(field.label == "Operator" for field in app.text_input))
                self.assertTrue(any("No runs yet" in info.value for info in app.info))
                self.assertFalse(any(field.label == "SQLite path" for field in app.text_input))
                upload_labels = {uploader.label for uploader in app.file_uploader}
                self.assertIn("Upload a non-empty SQLite snapshot", upload_labels)
                self.assertIn("Upload account policy Markdown", upload_labels)
                self.assertIn("Upload content Markdown *", upload_labels)
                self.assertNotIn("Hoặc upload nội dung gốc (.md/.txt)", upload_labels)
                labels = [tab.label for tab in app.tabs]
                self.assertIn("Create", labels)
                self.assertIn("Review", labels)
                self.assertIn("Publish", labels)
                self.assertIn("Channels", labels)
                self.assertIn("Analytics", labels)
                self.assertIn("Help", labels)
                self.assertTrue(any(button.label == "Test AI connections" for button in app.button))
                self.assertTrue(any(button.label == "Clear session keys" for button in app.button))
                self.assertFalse(
                    any(control.label == "Bạn muốn bắt đầu từ đâu?" for control in app.segmented_control)
                )
                gemini_key = next(field for field in app.text_input if field.label == "Gemini · Research")
                gemini_key.set_value("manual-session-test")
                app.run()
                self.assertEqual(list(app.exception), [])
                self.assertTrue(any("Session key active" in markdown.value for markdown in app.markdown))
                next(button for button in app.button if button.label == "Clear session keys").click()
                app.run()
                self.assertEqual(list(app.exception), [])
                self.assertTrue(any("system configuration" in info.value for info in app.info))
                self.assertFalse(any(field.label == "Chủ đề / Topic *" for field in app.text_input))
                self.assertFalse(
                    any(area.label == "Bạn muốn AI viết bài như thế nào? *" for area in app.text_area)
                )
                process_button = next(
                    button for button in app.button if button.label == "Continue with Markdown"
                )
                self.assertTrue(process_button.disabled)

                source = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
                self.assertIn("PipelineOrchestrator", source)
                self.assertIn("PolicyBuilderInput", source)
                self.assertIn("parse_content_markdown", source)
                self.assertNotIn("Type PUBLISH to unlock", source)
        finally:
            if previous is None:
                os.environ.pop("CONTENT_AGENT_DB", None)
            else:
                os.environ["CONTENT_AGENT_DB"] = previous

    def test_real_sqlite_review_queue_renders(self) -> None:
        previous = os.environ.get("CONTENT_AGENT_DB")
        try:
            with tempfile.TemporaryDirectory() as directory:
                database = Path(directory) / "review.sqlite3"
                store = SQLiteRunStore(database)
                policy = load_policy(FIXTURES / "policy_valid.md")
                research = ResearchBrief.model_validate_json(
                    (FIXTURES / "research_brief_valid.json").read_text(encoding="utf-8")
                ).model_copy(update={"account_id": policy.account_id})
                draft = DraftPost.model_validate_json(
                    (FIXTURES / "draft_post_valid.json").read_text(encoding="utf-8")
                ).model_copy(update={"account_id": policy.account_id, "brief_id": research.brief_id})
                critic = CriticResult.model_validate_json(
                    (FIXTURES / "critic_result_valid.json").read_text(encoding="utf-8")
                ).model_copy(
                    update={
                        "account_id": policy.account_id,
                        "draft_id": draft.draft_id,
                        "score": 92,
                        "decision": Decision.PASS,
                        "violations": [],
                    }
                )
                run_id = uuid4()
                store.start_run(
                    run_id=run_id,
                    topic=research.topic,
                    policy=policy,
                    source_path=FIXTURES / "policy_valid.md",
                )
                store.save_artifact(
                    run_id=run_id,
                    kind="research_brief",
                    entity_id=research.brief_id,
                    artifact=research,
                )
                store.save_artifact(
                    run_id=run_id,
                    kind="draft_post",
                    entity_id=draft.draft_id,
                    artifact=draft,
                )
                store.save_draft_revision(
                    run_id=run_id,
                    draft=draft,
                    revision=0,
                    origin=DraftOrigin.INITIAL_AI.value,
                )
                store.create_workflow(
                    run_id=run_id,
                    current_draft_id=draft.draft_id,
                    state="human_review",
                )
                store.save_critic_result(
                    run_id=run_id,
                    revision=0,
                    rule_result=RuleCritic().evaluate(draft=draft, policy=policy),
                    critic=critic,
                )
                store.complete_run(run_id)

                os.environ["CONTENT_AGENT_DB"] = str(database)
                app = AppTest.from_file(
                    str(ROOT / "streamlit_app.py"),
                    default_timeout=15,
                ).run()
                self.assertEqual(list(app.exception), [])
                review_select = next(box for box in app.selectbox if box.label == "Review item")
                self.assertEqual(review_select.value, str(run_id))
                self.assertTrue(any(draft.content in area.value for area in app.text_area))

                approve_button = next(
                    button
                    for button in app.button
                    if button.label == "Approve and continue to Publish"
                )
                approve_button.click()
                app.run()
                self.assertEqual(list(app.exception), [])
                self.assertTrue(any("Approved successfully" in success.value for success in app.success))
                self.assertTrue(any(f"--publish-approved {run_id}" in block.value for block in app.code))
                publish_select = next(box for box in app.selectbox if box.label == "Approved post")
                self.assertEqual(publish_select.value, str(run_id))
                self.assertEqual(store.get_workflow(run_id)["state"], "approved")
                self.assertEqual(
                    [action["action"] for action in store.get_review_actions(run_id)],
                    ["approve"],
                )
        finally:
            if previous is None:
                os.environ.pop("CONTENT_AGENT_DB", None)
            else:
                os.environ["CONTENT_AGENT_DB"] = previous

    def test_failed_run_without_draft_renders_in_history(self) -> None:
        previous = os.environ.get("CONTENT_AGENT_DB")
        try:
            with tempfile.TemporaryDirectory() as directory:
                database = Path(directory) / "failed-run.sqlite3"
                store = SQLiteRunStore(database)
                policy = load_policy(FIXTURES / "policy_valid.md")
                run_id = uuid4()
                store.start_run(
                    run_id=run_id,
                    topic="Provider unavailable",
                    policy=policy,
                    source_path=FIXTURES / "policy_valid.md",
                )
                store.fail_run(
                    run_id,
                    error_code="network",
                    error_message="Could not connect to provider.",
                )

                os.environ["CONTENT_AGENT_DB"] = str(database)
                app = AppTest.from_file(
                    str(ROOT / "streamlit_app.py"),
                    default_timeout=15,
                ).run()

                self.assertEqual(list(app.exception), [])
                self.assertTrue(
                    any(
                        "failed before a valid draft" in warning.value
                        for warning in app.warning
                    )
                )
        finally:
            if previous is None:
                os.environ.pop("CONTENT_AGENT_DB", None)
            else:
                os.environ["CONTENT_AGENT_DB"] = previous


if __name__ == "__main__":
    unittest.main()
