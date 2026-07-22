"""Deterministic policy checks used before the provider-backed LLM Critic."""

from __future__ import annotations

from enum import Enum

from pydantic import Field

from .ai.models import DraftPost, StrictModel
from .policy import AccountPolicy


class ViolationCode(str, Enum):
    EMPTY_CONTENT = "EMPTY_CONTENT"
    MAX_LENGTH = "MAX_LENGTH"
    BANNED_TERM = "BANNED_TERM"
    REQUIRED_HASHTAG = "REQUIRED_HASHTAG"
    INVALID_HASHTAG = "INVALID_HASHTAG"


class RuleViolation(StrictModel):
    code: ViolationCode
    message: str = Field(min_length=1)
    field: str = Field(min_length=1)
    observed: str | int | None = None
    expected: str | int | None = None


class RuleCriticResult(StrictModel):
    draft_id: str
    passed: bool
    rendered_length: int = Field(ge=0)
    violations: list[RuleViolation] = Field(default_factory=list)

    def messages(self) -> list[str]:
        return [f"[{violation.code.value}] {violation.message}" for violation in self.violations]


def render_post(draft: DraftPost) -> str:
    """Render the actual platform text used for deterministic length checks."""

    parts = [draft.content.strip()]
    if draft.call_to_action.strip():
        parts.append(draft.call_to_action.strip())
    if draft.hashtags:
        parts.append(" ".join(tag.strip() for tag in draft.hashtags if tag.strip()))
    return "\n\n".join(part for part in parts if part)


class RuleCritic:
    """Apply hard policy constraints that an LLM is never allowed to override."""

    def evaluate(self, *, draft: DraftPost, policy: AccountPolicy) -> RuleCriticResult:
        violations: list[RuleViolation] = []
        rendered = render_post(draft)

        if not draft.content.strip():
            violations.append(
                RuleViolation(
                    code=ViolationCode.EMPTY_CONTENT,
                    message="Draft content must not be empty.",
                    field="content",
                )
            )

        if len(rendered) > policy.max_length:
            violations.append(
                RuleViolation(
                    code=ViolationCode.MAX_LENGTH,
                    message=f"Rendered post has {len(rendered)} characters; maximum is {policy.max_length}.",
                    field="rendered_post",
                    observed=len(rendered),
                    expected=policy.max_length,
                )
            )

        searchable = "\n".join([draft.content, draft.call_to_action]).casefold()
        for banned_term in policy.banned_terms:
            if banned_term.casefold() in searchable:
                violations.append(
                    RuleViolation(
                        code=ViolationCode.BANNED_TERM,
                        message=f"Banned term '{banned_term}' appears in publishable text.",
                        field="content",
                        observed=banned_term,
                        expected="absent",
                    )
                )

        actual_hashtags = {tag.casefold() for tag in draft.hashtags}
        for required in policy.required_hashtags:
            if required.casefold() not in actual_hashtags:
                violations.append(
                    RuleViolation(
                        code=ViolationCode.REQUIRED_HASHTAG,
                        message=f"Required hashtag '{required}' is missing.",
                        field="hashtags",
                        observed="missing",
                        expected=required,
                    )
                )

        for hashtag in draft.hashtags:
            if not hashtag.startswith("#") or any(character.isspace() for character in hashtag):
                violations.append(
                    RuleViolation(
                        code=ViolationCode.INVALID_HASHTAG,
                        message=f"Hashtag '{hashtag}' must start with '#' and contain no whitespace.",
                        field="hashtags",
                        observed=hashtag,
                        expected="#SingleToken",
                    )
                )

        return RuleCriticResult(
            draft_id=str(draft.draft_id),
            passed=not violations,
            rendered_length=len(rendered),
            violations=violations,
        )
