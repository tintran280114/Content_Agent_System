"""Local mock Publisher with an authoritative persisted-state guard."""

from __future__ import annotations

from uuid import UUID

from .platform import SQLiteRunStore
from .workflow import PublishReceipt, PublishStatus, WorkflowState


class MockPublisher:
    """Record a publish receipt without calling any social-platform API."""

    ALLOWED_STATES = {WorkflowState.PASSED.value, WorkflowState.APPROVED.value}

    def __init__(self, store: SQLiteRunStore) -> None:
        self.store = store

    def publish(self, run_id: UUID | str) -> PublishReceipt:
        workflow = self.store.get_workflow(run_id)
        if not workflow:
            raise KeyError(f"workflow not found for run_id: {run_id}")
        draft = self.store.get_current_draft(run_id)
        state = str(workflow["state"])
        allowed = state in self.ALLOWED_STATES
        receipt = PublishReceipt(
            run_id=UUID(str(run_id)),
            draft_id=draft.draft_id,
            status=PublishStatus.PUBLISHED if allowed else PublishStatus.BLOCKED,
            reason=(
                f"Mock publish accepted from workflow state '{state}'."
                if allowed
                else f"Publisher guard blocked workflow state '{state}'."
            ),
        )
        self.store.add_publish_attempt(receipt=receipt)
        if allowed:
            self.store.update_workflow(
                run_id,
                state=WorkflowState.PUBLISHED.value,
                current_draft_id=draft.draft_id,
                rewrite_count=int(workflow["rewrite_count"]),
                expected_version=int(workflow["version"]),
            )
        return receipt
