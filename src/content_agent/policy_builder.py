"""Non-technical Markdown policy builder with the same strict parser contract."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field, field_validator, model_validator

from .ai.models import StrictModel
from .policy import AccountPolicy, parse_policy_text


class PolicyBuilderInput(StrictModel):
    """Friendly form contract used to render one canonical account policy."""

    display_name: str = Field(min_length=2, max_length=80)
    account_id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    active: bool = True
    goal: str = Field(min_length=10, max_length=500)
    audience: str = Field(min_length=3, max_length=300)
    platform: str = Field(min_length=1, max_length=50)
    tone: str = Field(min_length=3, max_length=300)
    language: str = Field(min_length=2, max_length=50)
    constraints: list[str] = Field(min_length=1, max_length=12)
    banned_terms: list[str] = Field(default_factory=list, max_length=20)
    required_hashtags: list[str] = Field(default_factory=list, max_length=12)
    examples: list[str] = Field(min_length=2, max_length=3)
    threshold: int = Field(default=80, ge=0, le=100)
    max_length: int = Field(default=500, ge=1, le=10_000)
    policy_compliance_weight: int = Field(default=40, ge=0, le=100)
    clarity_weight: int = Field(default=25, ge=0, le=100)
    usefulness_weight: int = Field(default=25, ge=0, le=100)
    originality_weight: int = Field(default=10, ge=0, le=100)
    adapter: str = "mock"
    target_id: str | None = None
    credential_ref: str | None = None
    approval_required: bool = True
    topic_tag: str | None = None
    topic_tag_candidates: list[str] = Field(default_factory=list, max_length=5)
    trend_search: bool = False

    @field_validator(
        "constraints",
        "banned_terms",
        "required_hashtags",
        "examples",
        "topic_tag_candidates",
    )
    @classmethod
    def clean_lists(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values if value.strip()]
        if len({value.casefold() for value in normalized}) != len(normalized):
            raise ValueError("list items must be unique")
        return normalized

    @field_validator("required_hashtags")
    @classmethod
    def normalize_hashtags(cls, values: list[str]) -> list[str]:
        return [value if value.startswith("#") else f"#{value}" for value in values]

    @field_validator("target_id", "credential_ref", "topic_tag", mode="before")
    @classmethod
    def blank_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def validate_builder(self) -> PolicyBuilderInput:
        total = (
            self.policy_compliance_weight
            + self.clarity_weight
            + self.usefulness_weight
            + self.originality_weight
        )
        if total != 100:
            raise ValueError(f"rubric weights must total 100, currently {total}")
        if self.adapter not in {"mock", "facebook_page", "threads", "linkedin"}:
            raise ValueError("adapter must be mock, facebook_page, threads, or linkedin")
        if self.adapter != "threads" and (self.topic_tag or self.topic_tag_candidates or self.trend_search):
            raise ValueError("topic/community tag settings are available only for Threads")
        return self


def split_lines(value: str) -> list[str]:
    """Convert a textarea into meaningful trimmed policy list items."""

    return [line.strip().removeprefix("-").strip() for line in value.splitlines() if line.strip()]


def _section(title: str, lines: list[str]) -> list[str]:
    if not lines:
        return []
    return [f"## {title}", *(f"- {line}" for line in lines), ""]


def render_policy_markdown(values: PolicyBuilderInput) -> str:
    """Render and re-parse Markdown so the UI cannot create an invalid policy."""

    publishing = [
        f"- adapter: {values.adapter}",
        f"- approval_required: {str(values.approval_required).lower()}",
    ]
    if values.adapter != "mock":
        publishing[1:1] = [
            f"- target_id: {values.target_id or ''}",
            f"- credential_ref: {values.credential_ref or ''}",
        ]
    if values.adapter == "threads":
        if values.topic_tag:
            publishing.append(f"- topic_tag: {values.topic_tag}")
        if values.topic_tag_candidates:
            publishing.append("- topic_tag_candidates: " + " | ".join(values.topic_tag_candidates))
        publishing.append(f"- trend_search: {str(values.trend_search).lower()}")

    lines = [
        f"# Account Policy: {values.display_name}",
        "",
        "## Account",
        f"- account_id: {values.account_id}",
        "- spec_version: 0.2",
        f"- active: {str(values.active).lower()}",
        "",
        "## Goal",
        values.goal,
        "",
        "## Audience",
        values.audience,
        "",
        "## Platform",
        values.platform,
        "",
        "## Tone",
        values.tone,
        "",
        "## Language",
        values.language,
        "",
        *_section("Constraints", values.constraints),
        *_section("Banned Terms", values.banned_terms),
        *_section("Required Hashtags", values.required_hashtags),
        *_section("Examples", values.examples),
        "## Rubric",
        f"- policy_compliance: {values.policy_compliance_weight}",
        f"- clarity: {values.clarity_weight}",
        f"- usefulness: {values.usefulness_weight}",
        f"- originality: {values.originality_weight}",
        "",
        "## Threshold",
        str(values.threshold),
        "",
        "## Maximum Length",
        str(values.max_length),
        "",
        "## Model Route",
        "- research: gemini@gemini-3.1-flash-lite",
        "- copywriter: groq@openai/gpt-oss-120b",
        "- critic: groq@openai/gpt-oss-20b",
        "",
        "## Publishing",
        *publishing,
        "",
    ]
    markdown = "\n".join(lines)
    parse_policy_text(markdown, source=f"{values.account_id}.md")
    return markdown


def save_policy_markdown(
    markdown: str,
    accounts_dir: str | Path,
    *,
    overwrite: bool = False,
) -> tuple[Path, AccountPolicy]:
    """Validate and atomically save an account policy inside accounts_dir."""

    policy = parse_policy_text(markdown, source="<policy-studio>")
    root = Path(accounts_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = (root / f"{policy.account_id}.md").resolve()
    if target.parent != root:
        raise ValueError("policy path must stay inside the accounts directory")
    if target.exists() and not overwrite:
        raise FileExistsError(f"{target.name} already exists; enable overwrite to replace it")
    temporary = target.with_name(f".{target.name}.tmp")
    try:
        temporary.write_text(markdown, encoding="utf-8")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target, policy
