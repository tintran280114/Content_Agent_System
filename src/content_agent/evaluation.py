"""Resumable fixed-set evaluation runner for 10 topics x three policies."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Callable

from .full_pipeline import FullPipelineError, FullPipelineOrchestrator
from .platform import SQLiteRunStore
from .policy import load_policy


class EvaluationRunner:
    def __init__(
        self,
        store: SQLiteRunStore,
        *,
        pipeline_factory: Callable[[SQLiteRunStore], FullPipelineOrchestrator] = FullPipelineOrchestrator,
    ) -> None:
        self.store = store
        self.pipeline_factory = pipeline_factory

    @staticmethod
    def case_key(evaluation_id: str, account_id: str, topic: str) -> str:
        raw = f"{evaluation_id}\0{account_id}\0{topic}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()[:24]

    def run(
        self,
        *,
        evaluation_id: str,
        topics: list[str],
        policy_paths: list[Path],
        resume: bool = True,
        limit: int | None = None,
        progress: Callable[[dict], None] | None = None,
    ) -> dict:
        existing = {
            row["case_key"]: row for row in self.store.list_evaluation_cases(evaluation_id)
        }
        cases = []
        for policy_path in policy_paths:
            policy = load_policy(policy_path)
            for topic in topics:
                cases.append((policy, policy_path, topic))
        if limit is not None:
            cases = cases[:limit]

        for policy, _, topic in cases:
            key = self.case_key(evaluation_id, policy.account_id, topic)
            if key not in existing or not resume:
                self.store.upsert_evaluation_case(
                    case_key=key,
                    evaluation_id=evaluation_id,
                    topic=topic,
                    account_id=policy.account_id,
                    status="pending",
                )

        for policy, policy_path, topic in cases:
            key = self.case_key(evaluation_id, policy.account_id, topic)
            if resume and existing.get(key, {}).get("status") == "completed":
                continue
            try:
                result = self.pipeline_factory(self.store).run(
                    topic=topic,
                    policy_path=policy_path,
                )
                self.store.upsert_evaluation_case(
                    case_key=key,
                    evaluation_id=evaluation_id,
                    topic=topic,
                    account_id=policy.account_id,
                    status="completed",
                    run_id=result.run_id,
                )
            except FullPipelineError as exc:
                self.store.upsert_evaluation_case(
                    case_key=key,
                    evaluation_id=evaluation_id,
                    topic=topic,
                    account_id=policy.account_id,
                    status="failed",
                    run_id=exc.run_id,
                    error_code=exc.code,
                    error_message=str(exc),
                )
            snapshot = self.report(evaluation_id)
            if progress:
                progress(snapshot)
        return self.report(evaluation_id)

    def report(self, evaluation_id: str) -> dict:
        cases = self.store.list_evaluation_cases(evaluation_id)
        completed = [case for case in cases if case["status"] == "completed"]
        failed = [case for case in cases if case["status"] == "failed"]
        runs = {row["run_id"]: row for row in self.store.list_runs(limit=10_000)}
        completed_runs = [runs[case["run_id"]] for case in completed if case["run_id"] in runs]
        scores = [row["score"] for row in completed_runs if row.get("score") is not None]
        usage = self.store.usage_summary()
        return {
            "evaluation_id": evaluation_id,
            "total_cases": len(cases),
            "completed": len(completed),
            "failed": len(failed),
            "pending": len(cases) - len(completed) - len(failed),
            "average_score": round(sum(scores) / len(scores), 2) if scores else None,
            "workflow_states": {
                state: sum(1 for row in completed_runs if row.get("workflow_state") == state)
                for state in sorted({row.get("workflow_state") for row in completed_runs if row.get("workflow_state")})
            },
            "usage": usage,
            "cases": cases,
        }


def write_report(path: str | Path, report: dict) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(output)
