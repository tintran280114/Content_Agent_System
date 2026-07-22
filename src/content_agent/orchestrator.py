"""Day 1 Policy -> Research -> Copywriter orchestration on one run_id."""

from __future__ import annotations

from pathlib import Path
from typing import Callable
from uuid import UUID, uuid4

from .ai.agents import CopywriterAgent, ResearchAgent
from .ai.base import StructuredProvider
from .ai.config import Role
from .ai.errors import ProviderError
from .ai.models import DraftPost, ResearchBrief, StrictModel
from .ai.registry import create_role_provider
from .platform import EventState, RunStep, SQLiteRunStore
from .policy import AccountPolicy, load_policy

ProviderFactory = Callable[[Role], StructuredProvider]


class Day1RunResult(StrictModel):
    run_id: UUID
    policy: AccountPolicy
    research: ResearchBrief
    draft: DraftPost


class Day1RunError(RuntimeError):
    def __init__(self, run_id: UUID, step: RunStep, code: str, message: str) -> None:
        self.run_id = run_id
        self.step = step
        self.code = code
        super().__init__(message)


class PipelineContractError(ValueError):
    """Safe internal error for a frozen handoff mismatch."""


class Day1Orchestrator:
    def __init__(
        self,
        store: SQLiteRunStore,
        *,
        provider_factory: ProviderFactory = create_role_provider,
    ) -> None:
        self.store = store
        self.provider_factory = provider_factory

    def _provider_for(self, role: Role, policy: AccountPolicy) -> StructuredProvider:
        provider = self.provider_factory(role)
        expected = policy.model_route[role.value]
        actual = provider.provider_name
        if actual != expected:
            raise PipelineContractError(
                f"Policy routes {role.value} to '{expected}', but the runtime selected '{actual}'."
            )
        return provider

    def run(self, *, topic: str, policy_path: str | Path) -> Day1RunResult:
        normalized_topic = topic.strip()
        if not normalized_topic:
            raise ValueError("topic must not be empty")

        source_path = Path(policy_path)
        policy = load_policy(source_path)
        run_id = uuid4()
        current_step = RunStep.POLICY
        self.store.start_run(
            run_id=run_id,
            topic=normalized_topic,
            policy=policy,
            source_path=source_path,
        )
        self.store.record_event(run_id=run_id, step=RunStep.RUN, state=EventState.STARTED)
        self.store.record_event(run_id=run_id, step=RunStep.POLICY, state=EventState.COMPLETED)

        try:
            current_step = RunStep.RESEARCH
            self.store.record_event(run_id=run_id, step=current_step, state=EventState.STARTED)
            research = ResearchAgent(self._provider_for(Role.RESEARCH, policy)).run(
                topic=normalized_topic,
                policy=policy,
            )
            self.store.save_artifact(
                run_id=run_id,
                kind="research_brief",
                entity_id=research.brief_id,
                artifact=research,
            )
            self.store.record_event(
                run_id=run_id,
                step=current_step,
                state=EventState.COMPLETED,
                provider=research.metadata.provider,
                model=research.metadata.model,
                usage=research.metadata.usage,
            )

            current_step = RunStep.COPYWRITER
            self.store.record_event(run_id=run_id, step=current_step, state=EventState.STARTED)
            draft = CopywriterAgent(self._provider_for(Role.COPYWRITER, policy)).run(
                research=research,
                policy=policy,
            )
            self.store.save_artifact(
                run_id=run_id,
                kind="draft_post",
                entity_id=draft.draft_id,
                artifact=draft,
            )
            self.store.record_event(
                run_id=run_id,
                step=current_step,
                state=EventState.COMPLETED,
                provider=draft.metadata.provider,
                model=draft.metadata.model,
                usage=draft.metadata.usage,
            )
            self.store.complete_run(run_id)
            self.store.record_event(run_id=run_id, step=RunStep.RUN, state=EventState.COMPLETED)
            return Day1RunResult(
                run_id=run_id,
                policy=policy,
                research=research,
                draft=draft,
            )
        except Exception as exc:
            if isinstance(exc, ProviderError):
                details = exc.as_dict()
                code = str(details["code"])
                message = str(details["message"])
                provider = str(details["provider"])
                model = str(details["model"])
                retryable = bool(details["retryable"])
                status_code = details["status_code"]
            elif isinstance(exc, PipelineContractError):
                code = "contract_mismatch"
                message = str(exc)
                provider = None
                model = None
                retryable = False
                status_code = None
            else:
                code = "pipeline_error"
                message = "Pipeline step failed; inspect the stored run event and retry."
                provider = None
                model = None
                retryable = False
                status_code = None

            self.store.record_event(
                run_id=run_id,
                step=current_step,
                state=EventState.FAILED,
                provider=provider,
                model=model,
                error_code=code,
                error_message=message,
                retryable=retryable,
                status_code=status_code,
            )
            self.store.fail_run(run_id, error_code=code, error_message=message)
            self.store.record_event(
                run_id=run_id,
                step=RunStep.RUN,
                state=EventState.FAILED,
                error_code=code,
                error_message=message,
                retryable=retryable,
                status_code=status_code,
            )
            raise Day1RunError(run_id, current_step, code, message) from exc
