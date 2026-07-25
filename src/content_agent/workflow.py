"""Safety workflow contracts shared by the pipeline, review service, and UI."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field

from .ai.models import ContentRequest, CriticResult, DraftPost, ResearchBrief, StrictModel
from .policy import AccountPolicy


class WorkflowState(StrEnum):
    DRAFTED = "drafted"
    DRAFTING = "drafting"
    CRITIQUING = "critiquing"
    REWRITING = "rewriting"
    PASSED = "passed"
    HUMAN_REVIEW = "human_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    DRY_RUN = "dry_run"
    PUBLISHED = "published"


class DraftOrigin(StrEnum):
    INITIAL_AI = "initial_ai"
    AI_REWRITE = "ai_rewrite"
    HUMAN_EDIT = "human_edit"


class ReviewActionType(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    EDIT = "edit"


class PublishStatus(StrEnum):
    PENDING = "pending"
    PUBLISHED = "published"
    BLOCKED = "blocked"
    DRY_RUN = "dry_run"
    FAILED = "failed"


class PublishReceipt(StrictModel):
    publish_id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    draft_id: UUID
    status: PublishStatus
    destination: str = "mock"
    idempotency_key: str = Field(default_factory=lambda: str(uuid4()), min_length=1)
    remote_post_id: str | None = None
    topic_tag: str | None = None
    http_status: int | None = Field(default=None, ge=100, le=599)
    attempt_count: int = Field(default=1, ge=0)
    reason: str = Field(min_length=1)


class PipelineResult(StrictModel):
    run_id: UUID
    mode: Literal["draft", "full"]
    request: ContentRequest | None = None
    policy: AccountPolicy
    research: ResearchBrief
    draft: DraftPost
    critic: CriticResult | None = None
    workflow_state: WorkflowState
    rewrite_count: int = Field(default=0, ge=0, le=2)
    publish_receipt: PublishReceipt | None = None
    terminal_error_code: str | None = None
    terminal_error_message: str | None = None
