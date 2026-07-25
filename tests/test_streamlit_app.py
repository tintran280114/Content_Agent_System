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
                self.assertEqual(app.title[0].value, "✨ Content Studio")
                self.assertTrue(any("No runs yet" in info.value for info in app.info))
                self.assertFalse(any(field.label == "SQLite path" for field in app.text_input))
                upload_labels = {uploader.label for uploader in app.file_uploader}
                self.assertIn("Upload a non-empty SQLite snapshot", upload_labels)
                self.assertIn("Upload account policy Markdown", upload_labels)
                self.assertNotIn("Hoặc upload nội dung gốc (.md/.txt)", upload_labels)
                labels = [tab.label for tab in app.tabs]
                self.assertIn("1 · Create content", labels)
                self.assertIn("2 · Review & approve", labels)
                self.assertIn("3 · Publish", labels)
                self.assertIn("4 · Accounts & policies", labels)
                self.assertIn("5 · Analytics", labels)
                self.assertIn("6 · Help & testing", labels)
                self.assertTrue(any(button.label == "Kiểm tra 3 kết nối" for button in app.button))
                self.assertTrue(any(button.label == "Xóa key nhập tay" for button in app.button))
                self.assertTrue(
                    any(control.label == "Bạn muốn bắt đầu từ đâu?" for control in app.segmented_control)
                )
                gemini_key = next(field for field in app.text_input if field.label == "Gemini · Research")
                gemini_key.set_value("manual-session-test")
                app.run()
                self.assertEqual(list(app.exception), [])
                self.assertTrue(any("Đang dùng key nhập tay" in markdown.value for markdown in app.markdown))
                next(button for button in app.button if button.label == "Xóa key nhập tay").click()
                app.run()
                self.assertEqual(list(app.exception), [])
                self.assertTrue(any("key mặc định của hệ thống" in info.value for info in app.info))
                self.assertTrue(any(field.label == "Chủ đề / Topic *" for field in app.text_input))
                self.assertTrue(
                    any(area.label == "Bạn muốn AI viết bài như thế nào? *" for area in app.text_area)
                )
                self.assertTrue(any(button.label == "✨ Tạo bài bằng AI" for button in app.button))
                generate_button = next(
                    button for button in app.button if button.label == "✨ Tạo bài bằng AI"
                )
                generate_button.click()
                app.run()
                self.assertEqual(list(app.exception), [])
                self.assertTrue(any("Hãy nhập chủ đề" in error.value for error in app.error))

                next(field for field in app.text_input if field.label == "Chủ đề / Topic *").set_value(
                    "Product launch"
                )
                next(button for button in app.button if button.label == "✨ Tạo bài bằng AI").click()
                app.run()
                self.assertEqual(list(app.exception), [])
                self.assertTrue(any("Hãy mô tả bài viết" in error.value for error in app.error))

                next(
                    control
                    for control in app.segmented_control
                    if control.label == "Bạn muốn bắt đầu từ đâu?"
                ).set_value("source")
                app.run()
                upload_labels = {uploader.label for uploader in app.file_uploader}
                self.assertIn("Hoặc upload nội dung gốc (.md/.txt)", upload_labels)
                next(button for button in app.button if button.label == "✨ Tạo bài bằng AI").click()
                app.run()
                self.assertEqual(list(app.exception), [])
                self.assertTrue(any("requires source content" in error.value for error in app.error))

                source = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
                self.assertIn("PipelineOrchestrator", source)
                self.assertIn("PolicyBuilderInput", source)
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
                        "score": 60,
                        "decision": Decision.HUMAN_REVIEW,
                        "violations": ["Needs a clearer practical step."],
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

                approve_actor = next(field for field in app.text_input if field.label == "Operator")
                approve_actor.set_value("boss@example.com")
                approve_button = next(
                    button for button in app.button if button.label == "Approve and move to Publish"
                )
                approve_button.click()
                app.run()
                self.assertEqual(list(app.exception), [])
                self.assertTrue(any("Approval failed" in error.value for error in app.error))
                self.assertEqual(store.get_workflow(run_id)["state"], "human_review")

                approval_note = next(
                    area for area in app.text_area if area.label == "Approval note (required)"
                )
                approval_note.set_value("Reviewed and approved for guarded publishing.")
                approve_button = next(
                    button for button in app.button if button.label == "Approve and move to Publish"
                )
                approve_button.click()
                app.run()

                self.assertEqual(list(app.exception), [])
                self.assertTrue(any("Approved successfully" in success.value for success in app.success))
                self.assertTrue(any(f"--publish-approved {run_id}" in block.value for block in app.code))
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


if __name__ == "__main__":
    unittest.main()
