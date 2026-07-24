"""Resumable fixed-set evaluation runner for 10 topics x three policies."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

from .orchestrator import PipelineOrchestrator, PipelineRunError
from .platform import SQLiteRunStore
from .policy import load_policy


class EvaluationRunner:
    def __init__(
        self,
        store: SQLiteRunStore,
        *,
        pipeline_factory: Callable[[SQLiteRunStore], PipelineOrchestrator] = PipelineOrchestrator,
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
            stop_for_quota = False
            try:
                result = self.pipeline_factory(self.store).run(
                    topic=topic,
                    policy_path=policy_path,
                )
                terminal_code = getattr(result, "terminal_error_code", None)
                self.store.upsert_evaluation_case(
                    case_key=key,
                    evaluation_id=evaluation_id,
                    topic=topic,
                    account_id=policy.account_id,
                    status="failed" if terminal_code else "completed",
                    run_id=result.run_id,
                    error_code=terminal_code,
                    error_message=getattr(result, "terminal_error_message", None),
                )
                stop_for_quota = terminal_code == "quota_exhausted"
            except PipelineRunError as exc:
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
                stop_for_quota = exc.code == "quota_exhausted"
            snapshot = self.report(evaluation_id)
            if progress:
                progress(snapshot)
            if stop_for_quota:
                break
        return self.report(evaluation_id)

    def report(self, evaluation_id: str) -> dict:
        cases = self.store.list_evaluation_cases(evaluation_id)
        completed = [case for case in cases if case["status"] == "completed"]
        failed = [case for case in cases if case["status"] == "failed"]
        runs = {row["run_id"]: row for row in self.store.list_runs(limit=10_000)}
        completed_runs = [runs[case["run_id"]] for case in completed if case["run_id"] in runs]
        scores = [row["score"] for row in completed_runs if row.get("score") is not None]
        records = [
            self._run_record(case=case, run=runs[case["run_id"]])
            for case in completed
            if case.get("run_id") in runs
        ]
        usage = self._evaluation_usage(records)
        return {
            "evaluation_id": evaluation_id,
            "total_cases": len(cases),
            "completed": len(completed),
            "failed": len(failed),
            "pending": len(cases) - len(completed) - len(failed),
            "quota_stopped": any(
                case.get("error_code") == "quota_exhausted" for case in failed
            ),
            "average_score": round(sum(scores) / len(scores), 2) if scores else None,
            "workflow_states": {
                state: sum(1 for row in completed_runs if row.get("workflow_state") == state)
                for state in sorted(
                    {
                        row.get("workflow_state")
                        for row in completed_runs
                        if row.get("workflow_state")
                    }
                )
            },
            "usage": usage,
            "per_account": self._per_account(records),
            "topic_comparisons": self._topic_comparisons(records),
            "generation_versions": self._generation_versions(records),
            "raw_outputs": records,
            "cases": cases,
        }

    def _run_record(self, *, case: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
        run_id = str(run["run_id"])
        policy = self.store.get_policy(run_id)
        research = self.store.get_research(run_id)
        draft = self.store.get_current_draft(run_id)
        critic = self.store.get_latest_critic(run_id)
        draft_revisions = self.store.get_draft_revisions(run_id)
        critic_results = self.store.get_critic_results(run_id)
        events = self.store.get_events(run_id)
        usage = self._event_usage(events)
        provider_usage = self._provider_usage(events)
        generations = [research.metadata.model_dump(mode="json")]
        generations.extend(
            revision["payload"]["metadata"]
            for revision in draft_revisions
        )
        generations.extend(
            result["payload"]["metadata"]
            for result in critic_results
        )
        return {
            "case_key": case["case_key"],
            "run_id": run_id,
            "account_id": run["account_id"],
            "topic": run["topic"],
            "policy_version": policy.spec_version,
            "workflow_state": run.get("workflow_state"),
            "rewrite_count": int(run.get("rewrite_count") or 0),
            "score": run.get("score"),
            "usage": usage,
            "provider_usage": provider_usage,
            "generation_metadata": generations,
            "research": research.model_dump(mode="json"),
            "draft": draft.model_dump(mode="json"),
            "critic": critic.model_dump(mode="json") if critic is not None else None,
            "draft_revisions": draft_revisions,
            "critic_results": critic_results,
        }

    @staticmethod
    def _event_usage(events: list[dict[str, Any]]) -> dict[str, Any]:
        provider_events = [event for event in events if event.get("provider")]
        requests = sum(event["state"] == "started" for event in provider_events)
        retries = sum(
            event["state"] == "failed" and bool(event.get("retryable"))
            for event in provider_events
        )
        completed = [event for event in provider_events if event["state"] == "completed"]
        costs = [
            float(event["estimated_cost_usd"])
            for event in completed
            if event.get("estimated_cost_usd") is not None
        ]
        return {
            "input_tokens": sum(int(event.get("input_tokens") or 0) for event in completed),
            "output_tokens": sum(int(event.get("output_tokens") or 0) for event in completed),
            "total_tokens": sum(int(event.get("total_tokens") or 0) for event in completed),
            "estimated_cost_usd": round(sum(costs), 8) if costs else None,
            "request_count": requests,
            "retry_count": retries,
            "retry_rate": round(retries / requests, 4) if requests else 0.0,
        }

    @staticmethod
    def _provider_usage(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for event in events:
            if event.get("provider"):
                groups[(str(event["provider"]), str(event.get("model") or "unknown"))].append(
                    event
                )
        return [
            {
                "provider": provider,
                "model": model,
                **EvaluationRunner._event_usage(provider_events),
            }
            for (provider, model), provider_events in sorted(groups.items())
        ]

    @staticmethod
    def _evaluation_usage(records: list[dict[str, Any]]) -> dict[str, Any]:
        total = EvaluationRunner._combine_usage(record["usage"] for record in records)
        provider_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for record in records:
            for usage in record["provider_usage"]:
                provider_groups[(usage["provider"], usage["model"])].append(usage)
        return {
            "total": total,
            "by_provider": [
                {
                    "provider": provider,
                    "model": model,
                    **EvaluationRunner._combine_usage(usages),
                }
                for (provider, model), usages in sorted(provider_groups.items())
            ],
            "by_run": [
                {
                    "run_id": record["run_id"],
                    "account_id": record["account_id"],
                    "topic": record["topic"],
                    **record["usage"],
                }
                for record in records
            ],
        }

    @staticmethod
    def _combine_usage(usages: Any) -> dict[str, Any]:
        rows = list(usages)
        requests = sum(int(row.get("request_count") or 0) for row in rows)
        retries = sum(int(row.get("retry_count") or 0) for row in rows)
        costs = [
            float(row["estimated_cost_usd"])
            for row in rows
            if row.get("estimated_cost_usd") is not None
        ]
        return {
            "input_tokens": sum(int(row.get("input_tokens") or 0) for row in rows),
            "output_tokens": sum(int(row.get("output_tokens") or 0) for row in rows),
            "total_tokens": sum(int(row.get("total_tokens") or 0) for row in rows),
            "estimated_cost_usd": round(sum(costs), 8) if costs else None,
            "request_count": requests,
            "retry_count": retries,
            "retry_rate": round(retries / requests, 4) if requests else 0.0,
        }

    @staticmethod
    def _per_account(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in records:
            groups[record["account_id"]].append(record)
        summaries = []
        for account_id, account_records in sorted(groups.items()):
            scores = [record["score"] for record in account_records if record.get("score") is not None]
            states = sorted({str(record["workflow_state"]) for record in account_records})
            summaries.append(
                {
                    "account_id": account_id,
                    "run_count": len(account_records),
                    "average_score": round(sum(scores) / len(scores), 2) if scores else None,
                    "workflow_states": {
                        state: sum(record["workflow_state"] == state for record in account_records)
                        for state in states
                    },
                    "usage": EvaluationRunner._combine_usage(
                        record["usage"] for record in account_records
                    ),
                }
            )
        return summaries

    @staticmethod
    def _topic_comparisons(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in records:
            groups[record["topic"]].append(record)
        comparisons = []
        for topic, topic_records in sorted(groups.items()):
            outputs = [
                {
                    "account_id": record["account_id"],
                    "run_id": record["run_id"],
                    "score": record["score"],
                    "content": record["draft"]["content"],
                }
                for record in topic_records
            ]
            comparisons.append(
                {
                    "topic": topic,
                    "account_count": len(outputs),
                    "distinct_output_count": len({output["content"] for output in outputs}),
                    "outputs": outputs,
                }
            )
        return comparisons

    @staticmethod
    def _generation_versions(records: list[dict[str, Any]]) -> list[dict[str, str]]:
        versions = {
            (
                metadata["role"],
                metadata["provider"],
                metadata["model"],
                metadata["prompt_version"],
                metadata["provider_sdk"],
            )
            for record in records
            for metadata in record["generation_metadata"]
        }
        return [
            {
                "role": role,
                "provider": provider,
                "model": model,
                "prompt_version": prompt_version,
                "provider_sdk": provider_sdk,
            }
            for role, provider, model, prompt_version, provider_sdk in sorted(versions)
        ]


def write_report(path: str | Path, report: dict) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(output)
