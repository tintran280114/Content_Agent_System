from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import _bootstrap  # noqa: F401

from content_agent.evaluation import EvaluationRunner, write_report
from content_agent.platform import SQLiteRunStore

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"


class FakePipeline:
    def __init__(self) -> None:
        self.calls = 0

    def run(self, *, topic: str, policy_path: Path):
        self.calls += 1
        return SimpleNamespace(run_id=uuid4())


class EvaluationTests(unittest.TestCase):
    def test_fixed_topic_set_contains_ten_topics(self) -> None:
        topics = json.loads((ROOT / "evaluation" / "topics.json").read_text(encoding="utf-8"))
        self.assertEqual(len(topics), 10)
        self.assertEqual(len(set(topics)), 10)

    def test_completed_cases_resume_without_duplicate_provider_calls(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteRunStore(Path(directory) / "evaluation.sqlite3")
            pipeline = FakePipeline()
            runner = EvaluationRunner(store, pipeline_factory=lambda _: pipeline)
            topics = ["Topic A", "Topic B"]
            first = runner.run(
                evaluation_id="test-v1",
                topics=topics,
                policy_paths=[FIXTURES / "policy_valid.md"],
            )
            second = runner.run(
                evaluation_id="test-v1",
                topics=topics,
                policy_paths=[FIXTURES / "policy_valid.md"],
                resume=True,
            )
            self.assertEqual(first["completed"], 2)
            self.assertEqual(second["completed"], 2)
            self.assertEqual(pipeline.calls, 2)

            output = Path(directory) / "report.json"
            write_report(output, second)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["completed"], 2)


if __name__ == "__main__":
    unittest.main()
