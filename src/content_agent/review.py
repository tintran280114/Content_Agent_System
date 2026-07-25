"""Audited human-review actions over the real SQLite workflow state."""

from __future__ import annotations

from uuid import UUID, uuid4

from .critics import RuleCritic
from .platform import SQLiteRunStore
from .publisher import MockPublisher, Publisher
from .workflow import DraftOrigin, PublishReceipt, ReviewActionType, WorkflowState


class ReviewService:
    def __init__(
        self,
        store: SQLiteRunStore,
        *,
        publisher: Publisher | None = None,
        rule_critic: RuleCritic | None = None,
        publish_on_approve: bool = True,
    ) -> None:
        self.store = store
        self.publisher = publisher or MockPublisher(store)
        self.rule_critic = rule_critic or RuleCritic()
        self.publish_on_approve = publish_on_approve

    @staticmethod
    def _identity(actor: str) -> str:
        normalized = actor.strip()
        if not normalized:
            raise ValueError("actor must not be empty")
        return normalized

    def approve(
        self,
        run_id: UUID | str,
        *,
        actor: str,
        note: str,
        expected_version: int | None = None,
    ) -> PublishReceipt | None:
        actor = self._identity(actor)
        note = note.strip()
        if not note:
            raise ValueError("approval note is required for a Critic override")
        workflow = self._require_human_review(run_id)
        version = int(workflow["version"]) if expected_version is None else expected_version
        draft = self.store.get_current_draft(run_id)
        rule_result = self.rule_critic.evaluate(draft=draft, policy=self.store.get_policy(run_id))
        if not rule_result.passed:
            codes = ", ".join(violation.code.value for violation in rule_result.violations)
            raise ValueError(f"hard policy violations must be edited before approval: {codes}")
        self.store.update_workflow(
            run_id,
            state=WorkflowState.APPROVED.value,
            current_draft_id=draft.draft_id,
            rewrite_count=int(workflow["rewrite_count"]),
            expected_version=version,
        )
        self.store.add_review_action(
            run_id=run_id,
            draft_id=draft.draft_id,
            action=ReviewActionType.APPROVE.value,
            actor=actor,
            note=note,
        )
        return self.publisher.publish(run_id) if self.publish_on_approve else None

    def reject(
        self,
        run_id: UUID | str,
        *,
        actor: str,
        note: str = "",
        expected_version: int | None = None,
    ) -> dict:
        actor = self._identity(actor)
        workflow = self._require_human_review(run_id)
        version = int(workflow["version"]) if expected_version is None else expected_version
        draft = self.store.get_current_draft(run_id)
        updated = self.store.update_workflow(
            run_id,
            state=WorkflowState.REJECTED.value,
            current_draft_id=draft.draft_id,
            rewrite_count=int(workflow["rewrite_count"]),
            expected_version=version,
        )
        self.store.add_review_action(
            run_id=run_id,
            draft_id=draft.draft_id,
            action=ReviewActionType.REJECT.value,
            actor=actor,
            note=note,
        )
        return updated

    def edit(
        self,
        run_id: UUID | str,
        *,
        actor: str,
        content: str,
        note: str = "",
        expected_version: int | None = None,
    ):
        actor = self._identity(actor)
        content = content.strip()
        if not content:
            raise ValueError("edited content must not be empty")
        workflow = self._require_human_review(run_id)
        version = int(workflow["version"]) if expected_version is None else expected_version
        current = self.store.get_current_draft(run_id)
        edited = current.model_copy(update={"draft_id": uuid4(), "content": content})
        revision = self.store.next_revision_number(run_id)
        self.store.save_draft_revision(
            run_id=run_id,
            draft=edited,
            revision=revision,
            origin=DraftOrigin.HUMAN_EDIT.value,
            parent_draft_id=current.draft_id,
        )
        self.store.update_workflow(
            run_id,
            state=WorkflowState.HUMAN_REVIEW.value,
            current_draft_id=edited.draft_id,
            rewrite_count=int(workflow["rewrite_count"]),
            expected_version=version,
        )
        self.store.add_review_action(
            run_id=run_id,
            draft_id=edited.draft_id,
            action=ReviewActionType.EDIT.value,
            actor=actor,
            note=note,
            edited_content=content,
        )
        return edited

    def _require_human_review(self, run_id: UUID | str) -> dict:
        workflow = self.store.get_workflow(run_id)
        if not workflow:
            raise KeyError(f"review item not found for run_id: {run_id}")
        if workflow["state"] != WorkflowState.HUMAN_REVIEW.value:
            raise ValueError(
                f"run {run_id} is '{workflow['state']}', not '{WorkflowState.HUMAN_REVIEW.value}'"
            )
        return workflow
