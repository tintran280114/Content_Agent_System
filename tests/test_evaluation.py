from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import _bootstrap  # noqa: F401
from content_agent.ai.models import (
    CriticResult,
    DraftPost,
    GenerationMetadata,
    ResearchBrief,
    TokenUsage,
)
from content_agent.critics import RuleCritic
from content_agent.evaluation import EvaluationRunner, write_report
from content_agent.platform import EventState, RunStep, SQLiteRunStore
from content_agent.policy import load_policy

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"


class FakePipeline:
    def __init__(self) -> None:
        self.calls = 0

    def run(self, *, topic: str, policy_path: Path):
        self.calls += 1
        return SimpleNamespace(run_id=uuid4())


class QuotaStoppedPipeline:
    def __init__(self) -> None:
        self.calls = 0

    def run(self, *, topic: str, policy_path: Path):
        self.calls += 1
        return SimpleNamespace(
            run_id=uuid4(),
            terminal_error_code="quota_exhausted",
            terminal_error_message="Application daily quota was exhausted.",
        )


class PersistingFakePipeline:
    """Deterministic fixture that exercises report persistence without network calls."""

    def __init__(self, store: SQLiteRunStore) -> None:
        self.store = store

    @staticmethod
    def metadata(*, provider: str, role: str) -> GenerationMetadata:
        return GenerationMetadata(
            provider=provider,
            model=f"{provider}-evaluation-test",
            role=role,
            prompt_version=f"{role}-v1.0.0",
            provider_sdk="fake/1.0",
            latency_ms=1,
            usage=TokenUsage(
                input_tokens=10,
                output_tokens=5,
                total_tokens=15,
                estimated_cost_usd=0.001,
            ),
        )

    def run(self, *, topic: str, policy_path: Path):
        policy = load_policy(policy_path)
        run_id = uuid4()
        self.store.start_run(
            run_id=run_id,
            topic=topic,
            policy=policy,
            source_path=policy_path,
        )
        research = ResearchBrief(
            topic=topic,
            account_id=policy.account_id,
            summary=f"Research for {policy.account_id} applies the complete account policy safely.",
            key_points=["Use the policy", "Keep human accountability"],
            audience_insights=[policy.audience],
            content_angles=[policy.goal],
            metadata=self.metadata(provider="gemini", role="research"),
        )
        draft = DraftPost(
            brief_id=research.brief_id,
            topic=topic,
            account_id=policy.account_id,
            platform=policy.platform,
            content=f"{policy.account_id}: {topic}. Apply written checks before publishing.",
            hashtags=policy.required_hashtags,
            policy_constraints_applied=policy.constraints,
            metadata=self.metadata(provider="groq", role="copywriter"),
        )
        critic = CriticResult(
            draft_id=draft.draft_id,
            account_id=policy.account_id,
            rule_passed=True,
            score=90,
            decision="pass",
            metadata=self.metadata(provider="github_models", role="critic"),
        )
        self.store.save_artifact(
            run_id=run_id,
            kind="research_brief",
            entity_id=research.brief_id,
            artifact=research,
        )
        self.store.save_artifact(
            run_id=run_id,
            kind="draft_post",
            entity_id=draft.draft_id,
            artifact=draft,
        )
        self.store.save_draft_revision(
            run_id=run_id,
            draft=draft,
            revision=0,
            origin="initial_ai",
        )
        self.store.create_workflow(
            run_id=run_id,
            current_draft_id=draft.draft_id,
            state="published",
        )
        self.store.save_critic_result(
            run_id=run_id,
            revision=0,
            rule_result=RuleCritic().evaluate(draft=draft, policy=policy),
            critic=critic,
        )
        for step, metadata in (
            (RunStep.RESEARCH, research.metadata),
            (RunStep.COPYWRITER, draft.metadata),
            (RunStep.LLM_CRITIC, critic.metadata),
        ):
            self.store.record_event(
                run_id=run_id,
                step=step,
                state=EventState.STARTED,
                provider=metadata.provider,
                model=metadata.model,
            )
            self.store.record_event(
                run_id=run_id,
                step=step,
                state=EventState.COMPLETED,
                provider=metadata.provider,
                model=metadata.model,
                usage=metadata.usage,
            )
        self.store.complete_run(run_id)
        return SimpleNamespace(run_id=run_id)


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

    def test_report_proves_policy_differences_and_usage_per_account(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteRunStore(Path(directory) / "evaluation.sqlite3")
            runner = EvaluationRunner(store, pipeline_factory=PersistingFakePipeline)
            report = runner.run(
                evaluation_id="comparison-v1",
                topics=["The same topic"],
                policy_paths=[
                    ROOT / "accounts" / "responsible-ai-lab.md",
                    ROOT / "accounts" / "startup-growth.md",
                    ROOT / "accounts" / "community-learning.md",
                ],
            )

            self.assertEqual(report["completed"], 3)
            self.assertEqual(len(report["raw_outputs"]), 3)
            self.assertEqual(report["topic_comparisons"][0]["account_count"], 3)
            self.assertEqual(report["topic_comparisons"][0]["distinct_output_count"], 3)
            self.assertEqual(report["usage"]["total"]["total_tokens"], 135)
            self.assertEqual(report["usage"]["total"]["request_count"], 9)
            self.assertEqual(report["usage"]["total"]["retry_rate"], 0.0)
            self.assertEqual(len(report["usage"]["by_provider"]), 3)
            self.assertEqual(len(report["per_account"]), 3)
            self.assertEqual(len(report["generation_versions"]), 3)
            self.assertEqual(len(report["raw_outputs"][0]["draft_revisions"]), 1)
            self.assertEqual(len(report["raw_outputs"][0]["critic_results"]), 1)

    def test_evaluation_checkpoints_and_stops_when_quota_is_exhausted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteRunStore(Path(directory) / "evaluation.sqlite3")
            pipeline = QuotaStoppedPipeline()
            runner = EvaluationRunner(store, pipeline_factory=lambda _: pipeline)

            report = runner.run(
                evaluation_id="quota-v1",
                topics=["Topic A", "Topic B"],
                policy_paths=[FIXTURES / "policy_valid.md"],
            )

            self.assertEqual(pipeline.calls, 1)
            self.assertEqual(report["failed"], 1)
            self.assertEqual(report["pending"], 1)
            self.assertTrue(report["quota_stopped"])


if __name__ == "__main__":
    unittest.main()
