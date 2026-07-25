"""Strict shared AI contracts for Research, Copywriter, and Critic handoffs."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    """Base contract that rejects accidental schema drift."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TokenUsage(StrictModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    estimated_cost_usd: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def total_covers_known_tokens(self) -> TokenUsage:
        known = self.input_tokens + self.output_tokens
        if self.total_tokens < known:
            self.total_tokens = known
        return self


class GenerationMetadata(StrictModel):
    provider: Literal["gemini", "groq", "github_models"]
    model: str = Field(min_length=1)
    role: Literal["research", "copywriter", "critic"]
    prompt_version: str = Field(min_length=1)
    provider_sdk: str = Field(min_length=1)
    latency_ms: int = Field(ge=0)
    usage: TokenUsage = Field(default_factory=TokenUsage)
    request_id: str | None = None
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PolicyContext(StrictModel):
    """Small compatibility view over Tài's AccountPolicy contract.

    The policy team remains the owner of parsing and validation. AI agents only
    normalize the fields they need, accepting a Pydantic model, dataclass-like
    object, or mapping.
    """

    account_id: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    audience: str = Field(default="general audience", min_length=1)
    platform: str = Field(default="generic social", min_length=1)
    tone: str = Field(default="clear and helpful", min_length=1)
    language: str = Field(default="English", min_length=1)
    constraints: list[str] = Field(default_factory=list)
    banned_terms: list[str] = Field(default_factory=list)
    required_hashtags: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)
    rubric: dict[str, int] = Field(default_factory=dict)
    threshold: int = Field(default=75, ge=0, le=100)
    max_length: int | None = Field(default=None, ge=1)

    @classmethod
    def from_policy(cls, policy: Any) -> PolicyContext:
        if isinstance(policy, cls):
            return policy
        if isinstance(policy, BaseModel):
            raw: Mapping[str, Any] = policy.model_dump()
        elif isinstance(policy, Mapping):
            raw = policy
        elif hasattr(policy, "__dict__"):
            raw = vars(policy)
        else:
            raise TypeError("policy must be a mapping, Pydantic model, or object with attributes")

        data = dict(raw)
        data.setdefault(
            "account_id",
            data.get("account") or data.get("slug") or data.get("name"),
        )
        # Tài's canonical contract can contain parser/version/routing fields the
        # AI layer does not consume. Keep the normalized view strict while
        # deliberately selecting only the agreed handoff fields here.
        selected = {key: value for key, value in data.items() if key in cls.model_fields}
        return cls.model_validate(selected)


class ContentTask(StrEnum):
    """Operator intent for the source material supplied to the pipeline."""

    CREATE = "create"
    REPURPOSE = "repurpose"
    REWRITE = "rewrite"
    SUMMARIZE = "summarize"


class ContentSource(StrEnum):
    """How source content entered the system."""

    NONE = "none"
    PASTED = "pasted"
    FILE = "file"


class ContentRequest(StrictModel):
    """Frozen operator input kept separate from AI-generated content."""

    request_id: UUID = Field(default_factory=uuid4)
    topic: str = Field(min_length=1, max_length=500)
    instructions: str = Field(default="", max_length=5_000)
    source_content: str = Field(default="", max_length=30_000)
    source_name: str | None = Field(default=None, max_length=255)
    source_type: ContentSource = ContentSource.NONE
    task: ContentTask = ContentTask.CREATE

    @model_validator(mode="after")
    def validate_source_and_task(self) -> ContentRequest:
        has_source = bool(self.source_content)
        if self.source_type == ContentSource.NONE and has_source:
            raise ValueError("source_type must describe supplied source_content")
        if self.source_type != ContentSource.NONE and not has_source:
            raise ValueError("source_content is required for pasted or file input")
        if self.source_type == ContentSource.FILE and not self.source_name:
            raise ValueError("source_name is required for file input")
        if self.source_type != ContentSource.FILE and self.source_name:
            raise ValueError("source_name is available only for file input")
        if self.task != ContentTask.CREATE and not has_source:
            raise ValueError(f"task '{self.task.value}' requires source content")
        return self

    @classmethod
    def from_inputs(
        cls,
        *,
        topic: str,
        instructions: str = "",
        source_content: str = "",
        source_name: str | None = None,
        task: ContentTask | str = ContentTask.CREATE,
    ) -> ContentRequest:
        normalized_source = source_content.strip()
        normalized_name = source_name.strip() if source_name else None
        if normalized_source:
            source_type = ContentSource.FILE if normalized_name else ContentSource.PASTED
        else:
            source_type = ContentSource.NONE
            normalized_name = None
        return cls(
            topic=topic,
            instructions=instructions,
            source_content=normalized_source,
            source_name=normalized_name,
            source_type=source_type,
            task=task,
        )

    @property
    def has_source_content(self) -> bool:
        return bool(self.source_content)


class ResearchPayload(StrictModel):
    """Provider-generated portion of a ResearchBrief."""

    summary: str = Field(min_length=20)
    key_points: list[str] = Field(min_length=2, max_length=8)
    audience_insights: list[str] = Field(min_length=1, max_length=6)
    content_angles: list[str] = Field(min_length=1, max_length=6)
    risks: list[str] = Field(default_factory=list, max_length=6)
    source_notes: list[str] = Field(default_factory=list, max_length=8)


class ResearchBrief(ResearchPayload):
    brief_id: UUID = Field(default_factory=uuid4)
    request_id: UUID | None = None
    topic: str = Field(min_length=1)
    account_id: str = Field(min_length=1)
    metadata: GenerationMetadata


class DraftPayload(StrictModel):
    """Provider-generated portion of a DraftPost."""

    content: str = Field(min_length=1)
    hashtags: list[str] = Field(default_factory=list, max_length=12)
    call_to_action: str = ""
    policy_constraints_applied: list[str] = Field(default_factory=list)


class DraftPost(DraftPayload):
    draft_id: UUID = Field(default_factory=uuid4)
    brief_id: UUID
    request_id: UUID | None = None
    topic: str = Field(min_length=1)
    account_id: str = Field(min_length=1)
    platform: str = Field(min_length=1)
    metadata: GenerationMetadata


class Decision(StrEnum):
    PASS = "pass"
    REWRITE = "rewrite"
    HUMAN_REVIEW = "human_review"


class CriticPayload(StrictModel):
    """Provider-generated portion of a CriticResult."""

    rule_passed: bool
    score: int = Field(ge=0, le=100)
    violations: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    decision: Decision


class CriticResult(CriticPayload):
    critic_id: UUID = Field(default_factory=uuid4)
    draft_id: UUID
    account_id: str = Field(min_length=1)
    metadata: GenerationMetadata


class ResearchCopywriterResult(StrictModel):
    research: ResearchBrief
    draft: DraftPost
