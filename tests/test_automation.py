from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class AutomationTests(unittest.TestCase):
    def test_scheduled_workflow_uses_cli_not_streamlit(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "batch.yml").read_text(encoding="utf-8")
        self.assertIn('cron: "17 8,20 * * *"', workflow)
        self.assertIn('timezone: "Asia/Ho_Chi_Minh"', workflow)
        self.assertIn("python run.py --all --pipeline full", workflow)
        self.assertIn(
            "CONTENT_AGENT_PUBLISH_MODE: ${{ vars.CONTENT_AGENT_PUBLISH_MODE || 'dry-run' }}", workflow
        )
        self.assertIn("--publish-mode", workflow)
        self.assertIn("secrets.THREADS_RESPONSIBLE_AI_TOKEN", workflow)
        self.assertNotIn("streamlit run", workflow)

    def test_scheduled_workflow_retains_sqlite_handoff(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "batch.yml").read_text(encoding="utf-8")
        self.assertIn("Restore the latest SQLite snapshot", workflow)
        self.assertIn("name: content-agent-latest", workflow)
        self.assertIn("path: artifacts/content_agent.sqlite3", workflow)


if __name__ == "__main__":
    unittest.main()
