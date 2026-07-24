"""Safety workflow contracts shared by the pipeline, review service, and UI."""

from __future__ import annotations

from enum import Enum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field

from .ai.models import CriticResult, DraftPost, ResearchBrief, StrictModel
from .policy import AccountPolicy


class WorkflowState(str, Enum):
    DRAFTED = "drafted"
    DRAFTING = "drafting"
    CRITIQUING = "critiquing"
    REWRITING = "rewriting"
    PASSED = "passed"
    HUMAN_REVIEW = "human_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    PUBLISHED = "published"


class DraftOrigin(str, Enum):
    INITIAL_AI = "initial_ai"
    AI_REWRITE = "ai_rewrite"
    HUMAN_EDIT = "human_edit"


class ReviewActionType(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    EDIT = "edit"


class PublishStatus(str, Enum):
    PUBLISHED = "published"
    BLOCKED = "blocked"


class PublishReceipt(StrictModel):
    publish_id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    draft_id: UUID
    status: PublishStatus
    destination: str = "mock"
    reason: str = Field(min_length=1)


class PipelineResult(StrictModel):
    run_id: UUID
    mode: Literal["draft", "full"]
    policy: AccountPolicy
    research: ResearchBrief
    draft: DraftPost
    critic: CriticResult | None = None
    workflow_state: WorkflowState
    rewrite_count: int = Field(default=0, ge=0, le=2)
    publish_receipt: PublishReceipt | None = None
    terminal_error_code: str | None = None
    terminal_error_message: str | None = None
