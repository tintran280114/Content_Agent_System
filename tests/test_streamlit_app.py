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
                self.assertEqual(app.title[0].value, "Social Content Operations")
                self.assertTrue(any("No run data yet" in info.value for info in app.info))
                self.assertFalse(any(field.label == "SQLite path" for field in app.text_input))
                self.assertEqual(len(app.file_uploader), 1)
                labels = [tab.label for tab in app.tabs]
                self.assertIn("Human review", labels)
                self.assertIn("Scores & usage", labels)
                self.assertNotIn("Run batch", labels)
                self.assertNotIn("Evidence", labels)
                source = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
                self.assertNotIn("PipelineOrchestrator", source)
                self.assertNotIn("BatchService", source)
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
                ).model_copy(
                    update={"account_id": policy.account_id, "brief_id": research.brief_id}
                )
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
        finally:
            if previous is None:
                os.environ.pop("CONTENT_AGENT_DB", None)
            else:
                os.environ["CONTENT_AGENT_DB"] = previous


if __name__ == "__main__":
    unittest.main()
