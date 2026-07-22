"""Frozen PLT-01 run-state and event contracts."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import UUID

from pydantic import Field

from ..ai.models import StrictModel, TokenUsage


class RunState(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class RunStep(str, Enum):
    RUN = "run"
    POLICY = "policy"
    RESEARCH = "research"
    COPYWRITER = "copywriter"
    RULE_CRITIC = "rule_critic"
    LLM_CRITIC = "llm_critic"
    REWRITE = "rewrite"
    HUMAN_REVIEW = "human_review"
    PUBLISHER = "publisher"


class EventState(str, Enum):
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"


class RunEvent(StrictModel):
    event_id: int | None = Field(default=None, ge=1)
    run_id: UUID
    step: RunStep
    state: EventState
    attempt: int = Field(default=1, ge=1)
    provider: str | None = None
    model: str | None = None
    usage: TokenUsage = Field(default_factory=TokenUsage)
    error_code: str | None = None
    error_message: str | None = None
    retryable: bool = False
    status_code: int | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
