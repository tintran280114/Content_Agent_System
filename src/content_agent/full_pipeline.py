"""Wednesday-MVP hybrid Critic, rewrite, review, and mock-publish pipeline."""

from __future__ import annotations

import time
from enum import Enum
from pathlib import Path
from typing import Callable, TypeVar
from uuid import UUID, uuid4

from .ai.agents import CopywriterAgent, CriticAgent, ResearchAgent, RewriteAgent
from .ai.base import StructuredProvider
from .ai.config import Role
from .ai.errors import ProviderError
from .ai.models import CriticResult, Decision, DraftPost, GenerationMetadata, ResearchBrief
from .ai.registry import create_role_provider
from .critics import RuleCritic
from .platform import EventState, RunStep, SQLiteRunStore
from .policy import AccountPolicy, load_policy
from .publisher import MockPublisher, Publisher
from .quota import QuotaManager
from .workflow import DraftOrigin, PipelineResult, WorkflowState

ProviderFactory = Callable[[Role], StructuredProvider]
SleepFunction = Callable[[float], None]
ResultT = TypeVar("ResultT", ResearchBrief, DraftPost, CriticResult)


class PipelineMode(str, Enum):
    DRAFT = "draft"
    FULL = "full"


class PipelineContractError(ValueError):
    """Safe internal error for a frozen handoff mismatch."""


class PipelineRunError(RuntimeError):
    def __init__(self, run_id: UUID, step: RunStep, code: str, message: str) -> None:
        self.run_id = run_id
        self.step = step
        self.code = code
        super().__init__(message)


class PipelineOrchestrator:
    MAX_REWRITES = 2

    def __init__(
        self,
        store: SQLiteRunStore,
        *,
        provider_factory: ProviderFactory = create_role_provider,
        rule_critic: RuleCritic | None = None,
        publisher: Publisher | None = None,
        quota_manager: QuotaManager | None = None,
        max_provider_attempts: int = 3,
        base_backoff_seconds: float = 1.0,
        sleeper: SleepFunction = time.sleep,
    ) -> None:
        if max_provider_attempts < 1:
            raise ValueError("max_provider_attempts must be at least 1")
        self.store = store
        self.provider_factory = provider_factory
        self.rule_critic = rule_critic or RuleCritic()
        self.publisher = publisher or MockPublisher(store)
        self.quota_manager = quota_manager or QuotaManager(store)
        self.max_provider_attempts = max_provider_attempts
        self.base_backoff_seconds = max(0.0, base_backoff_seconds)
        self.sleeper = sleeper

    def _provider_for(self, role: Role, policy: AccountPolicy) -> StructuredProvider:
        provider = self.provider_factory(role)
        expected = policy.model_route[role.value]
        if provider.provider_name != expected:
            raise PipelineContractError(
                f"Policy routes {role.value} to '{expected}', "
                f"but the runtime selected '{provider.provider_name}'."
            )
        return provider

    def _provider_step(
        self,
        *,
        run_id: UUID,
        step: RunStep,
        provider: StructuredProvider,
        operation: Callable[[], ResultT],
    ) -> ResultT:
        for attempt in range(1, self.max_provider_attempts + 1):
            self.quota_manager.ensure_available(
                provider=provider.provider_name,
                model=provider.model,
            )
            self.store.record_event(
                run_id=run_id,
                step=step,
                state=EventState.STARTED,
                attempt=attempt,
                provider=provider.provider_name,
                model=provider.model,
            )
            try:
                result = operation()
            except ProviderError as exc:
                details = exc.as_dict()
                self.store.record_event(
                    run_id=run_id,
                    step=step,
                    state=EventState.FAILED,
                    attempt=attempt,
                    provider=str(details["provider"]),
                    model=str(details["model"]),
                    error_code=str(details["code"]),
                    error_message=str(details["message"]),
                    retryable=bool(details["retryable"]),
                    status_code=details["status_code"],
                )
                if not exc.retryable or attempt >= self.max_provider_attempts:
                    raise
                self.sleeper(self.base_backoff_seconds * (2 ** (attempt - 1)))
                continue

            metadata: GenerationMetadata = result.metadata
            self.store.record_event(
                run_id=run_id,
                step=step,
                state=EventState.COMPLETED,
                attempt=attempt,
                provider=metadata.provider,
                model=metadata.model,
                usage=metadata.usage,
            )
            return result
        raise AssertionError("provider attempt loop exited unexpectedly")

    @staticmethod
    def _safe_error(exc: Exception) -> tuple[str, str, bool]:
        if isinstance(exc, ProviderError):
            return exc.code.value, str(exc), exc.retryable
        if isinstance(exc, PipelineContractError):
            return "contract_mismatch", str(exc), False
        return "pipeline_error", "Pipeline step failed; inspect stored events and retry.", False

    def run(
        self,
        *,
        topic: str,
        policy_path: str | Path,
        mode: PipelineMode | str = PipelineMode.FULL,
    ) -> PipelineResult:
        normalized_topic = topic.strip()
        if not normalized_topic:
            raise ValueError("topic must not be empty")
        normalized_mode = mode if isinstance(mode, PipelineMode) else PipelineMode(mode)
        source_path = Path(policy_path)
        policy = load_policy(source_path)
        run_id = uuid4()
        current_step = RunStep.POLICY
        research: ResearchBrief | None = None
        current_draft: DraftPost | None = None
        latest_critic: CriticResult | None = None
        rewrite_count = 0

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
            research_provider = self._provider_for(Role.RESEARCH, policy)
            research = self._provider_step(
                run_id=run_id,
                step=current_step,
                provider=research_provider,
                operation=lambda: ResearchAgent(research_provider).run(
                    topic=normalized_topic,
                    policy=policy,
                ),
            )
            self.store.save_artifact(
                run_id=run_id,
                kind="research_brief",
                entity_id=research.brief_id,
                artifact=research,
            )

            current_step = RunStep.COPYWRITER
            copywriter_provider = self._provider_for(Role.COPYWRITER, policy)
            current_draft = self._provider_step(
                run_id=run_id,
                step=current_step,
                provider=copywriter_provider,
                operation=lambda: CopywriterAgent(copywriter_provider).run(
                    research=research,
                    policy=policy,
                ),
            )
            self.store.save_artifact(
                run_id=run_id,
                kind="draft_post",
                entity_id=current_draft.draft_id,
                artifact=current_draft,
            )
            self.store.save_draft_revision(
                run_id=run_id,
                draft=current_draft,
                revision=0,
                origin=DraftOrigin.INITIAL_AI.value,
            )
            if normalized_mode == PipelineMode.DRAFT:
                self.store.create_workflow(
                    run_id=run_id,
                    current_draft_id=current_draft.draft_id,
                    state=WorkflowState.DRAFTED.value,
                )
                self.store.complete_run(run_id)
                self.store.record_event(
                    run_id=run_id,
                    step=RunStep.RUN,
                    state=EventState.COMPLETED,
                )
                return PipelineResult(
                    run_id=run_id,
                    mode=normalized_mode.value,
                    policy=policy,
                    research=research,
                    draft=current_draft,
                    workflow_state=WorkflowState.DRAFTED,
                )
            self.store.create_workflow(
                run_id=run_id,
                current_draft_id=current_draft.draft_id,
                state=WorkflowState.CRITIQUING.value,
            )

            while True:
                current_step = RunStep.RULE_CRITIC
                self.store.record_event(
                    run_id=run_id,
                    step=current_step,
                    state=EventState.STARTED,
                    attempt=rewrite_count + 1,
                )
                rule_result = self.rule_critic.evaluate(draft=current_draft, policy=policy)
                self.store.record_event(
                    run_id=run_id,
                    step=current_step,
                    state=EventState.COMPLETED,
                    attempt=rewrite_count + 1,
                )

                current_step = RunStep.LLM_CRITIC
                critic_provider = self._provider_for(Role.CRITIC, policy)
                latest_critic = self._provider_step(
                    run_id=run_id,
                    step=current_step,
                    provider=critic_provider,
                    operation=lambda: CriticAgent(critic_provider).run(
                        draft=current_draft,
                        policy=policy,
                        rule_result=rule_result,
                    ),
                )
                if latest_critic.decision != Decision.PASS and rewrite_count >= self.MAX_REWRITES:
                    latest_critic = latest_critic.model_copy(
                        update={"decision": Decision.HUMAN_REVIEW}
                    )
                self.store.save_critic_result(
                    run_id=run_id,
                    revision=rewrite_count,
                    rule_result=rule_result,
                    critic=latest_critic,
                )

                if latest_critic.decision == Decision.PASS:
                    workflow = self.store.get_workflow(run_id)
                    self.store.update_workflow(
                        run_id,
                        state=WorkflowState.PASSED.value,
                        current_draft_id=current_draft.draft_id,
                        rewrite_count=rewrite_count,
                        expected_version=int(workflow["version"]),
                    )
                    current_step = RunStep.PUBLISHER
                    self.store.record_event(
                        run_id=run_id,
                        step=current_step,
                        state=EventState.STARTED,
                    )
                    receipt = self.publisher.publish(run_id)
                    self.store.record_event(
                        run_id=run_id,
                        step=current_step,
                        state=EventState.COMPLETED,
                    )
                    self.store.complete_run(run_id)
                    self.store.record_event(
                        run_id=run_id,
                        step=RunStep.RUN,
                        state=EventState.COMPLETED,
                    )
                    return PipelineResult(
                        run_id=run_id,
                        mode=normalized_mode.value,
                        policy=policy,
                        research=research,
                        draft=current_draft,
                        critic=latest_critic,
                        workflow_state=WorkflowState.PUBLISHED,
                        rewrite_count=rewrite_count,
                        publish_receipt=receipt,
                    )

                if rewrite_count >= self.MAX_REWRITES:
                    workflow = self.store.get_workflow(run_id)
                    self.store.update_workflow(
                        run_id,
                        state=WorkflowState.HUMAN_REVIEW.value,
                        current_draft_id=current_draft.draft_id,
                        rewrite_count=rewrite_count,
                        expected_version=int(workflow["version"]),
                    )
                    self.store.record_event(
                        run_id=run_id,
                        step=RunStep.HUMAN_REVIEW,
                        state=EventState.COMPLETED,
                    )
                    self.store.complete_run(run_id)
                    self.store.record_event(
                        run_id=run_id,
                        step=RunStep.RUN,
                        state=EventState.COMPLETED,
                    )
                    return PipelineResult(
                        run_id=run_id,
                        mode=normalized_mode.value,
                        policy=policy,
                        research=research,
                        draft=current_draft,
                        critic=latest_critic,
                        workflow_state=WorkflowState.HUMAN_REVIEW,
                        rewrite_count=rewrite_count,
                    )

                rewrite_count += 1
                workflow = self.store.get_workflow(run_id)
                self.store.update_workflow(
                    run_id,
                    state=WorkflowState.REWRITING.value,
                    current_draft_id=current_draft.draft_id,
                    rewrite_count=rewrite_count,
                    expected_version=int(workflow["version"]),
                )
                previous_draft = current_draft
                current_step = RunStep.REWRITE
                current_draft = self._provider_step(
                    run_id=run_id,
                    step=current_step,
                    provider=copywriter_provider,
                    operation=lambda: RewriteAgent(copywriter_provider).run(
                        research=research,
                        draft=previous_draft,
                        critic=latest_critic,
                        policy=policy,
                        rewrite_number=rewrite_count,
                    ),
                )
                self.store.save_draft_revision(
                    run_id=run_id,
                    draft=current_draft,
                    revision=rewrite_count,
                    origin=DraftOrigin.AI_REWRITE.value,
                    parent_draft_id=previous_draft.draft_id,
                )
                workflow = self.store.get_workflow(run_id)
                self.store.update_workflow(
                    run_id,
                    state=WorkflowState.CRITIQUING.value,
                    current_draft_id=current_draft.draft_id,
                    rewrite_count=rewrite_count,
                    expected_version=int(workflow["version"]),
                )
        except Exception as exc:
            code, message, retryable = self._safe_error(exc)
            failure_already_recorded = any(
                event["step"] == current_step.value
                and event["state"] == EventState.FAILED.value
                and event["error_code"] == code
                for event in self.store.get_events(run_id)
            )
            if not failure_already_recorded:
                provider = exc.provider if isinstance(exc, ProviderError) else None
                model = exc.model if isinstance(exc, ProviderError) else None
                status_code = exc.status_code if isinstance(exc, ProviderError) else None
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
            if current_draft is not None and self.store.get_workflow(run_id):
                workflow = self.store.get_workflow(run_id)
                self.store.update_workflow(
                    run_id,
                    state=WorkflowState.HUMAN_REVIEW.value,
                    current_draft_id=current_draft.draft_id,
                    rewrite_count=rewrite_count,
                    last_error_code=code,
                    last_error_message=message,
                    expected_version=int(workflow["version"]),
                )
                self.store.record_event(
                    run_id=run_id,
                    step=RunStep.HUMAN_REVIEW,
                    state=EventState.COMPLETED,
                    error_code=code,
                    error_message=message,
                    retryable=retryable,
                )
                self.store.complete_run(run_id)
                self.store.record_event(
                    run_id=run_id,
                    step=RunStep.RUN,
                    state=EventState.COMPLETED,
                    error_code=code,
                    error_message=message,
                    retryable=retryable,
                )
                return PipelineResult(
                    run_id=run_id,
                    mode=normalized_mode.value,
                    policy=policy,
                    research=research,
                    draft=current_draft,
                    critic=latest_critic,
                    workflow_state=WorkflowState.HUMAN_REVIEW,
                    rewrite_count=rewrite_count,
                    terminal_error_code=code,
                    terminal_error_message=message,
                )

            self.store.fail_run(run_id, error_code=code, error_message=message)
            self.store.record_event(
                run_id=run_id,
                step=RunStep.RUN,
                state=EventState.FAILED,
                error_code=code,
                error_message=message,
                retryable=retryable,
            )
            raise PipelineRunError(run_id, current_step, code, message) from exc
