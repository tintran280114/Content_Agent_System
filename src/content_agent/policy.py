"""Versioned Markdown account-policy contract and parser for POL-01."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from pydantic import Field, ValidationError, field_validator, model_validator

from .ai.models import StrictModel

POLICY_SPEC_VERSION = "0.1"

_REQUIRED_SECTIONS = {
    "account",
    "goal",
    "audience",
    "platform",
    "tone",
    "language",
    "constraints",
    "examples",
    "rubric",
    "threshold",
    "maximum length",
    "model route",
}
_OPTIONAL_SECTIONS = {"banned terms", "required hashtags"}
_FIELD_TO_SECTION = {
    "spec_version": "Account",
    "account_id": "Account",
    "goal": "Goal",
    "audience": "Audience",
    "platform": "Platform",
    "tone": "Tone",
    "language": "Language",
    "constraints": "Constraints",
    "banned_terms": "Banned Terms",
    "required_hashtags": "Required Hashtags",
    "examples": "Examples",
    "rubric": "Rubric",
    "threshold": "Threshold",
    "max_length": "Maximum Length",
    "model_route": "Model Route",
}


class AccountPolicy(StrictModel):
    """Canonical Policy Spec v0.1 object shared by all Day 1 owners."""

    spec_version: str = Field(pattern=r"^0\.1$")
    account_id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    goal: str = Field(min_length=10)
    audience: str = Field(min_length=3)
    platform: str = Field(min_length=1)
    tone: str = Field(min_length=3)
    language: str = Field(min_length=2)
    constraints: list[str] = Field(min_length=1)
    banned_terms: list[str] = Field(default_factory=list)
    required_hashtags: list[str] = Field(default_factory=list)
    examples: list[str] = Field(min_length=1)
    rubric: dict[str, int] = Field(min_length=1)
    threshold: int = Field(ge=0, le=100)
    max_length: int = Field(ge=1, le=10_000)
    model_route: dict[str, str]

    @field_validator("constraints", "banned_terms", "required_hashtags", "examples")
    @classmethod
    def list_items_are_unique_and_non_empty(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value for value in normalized):
            raise ValueError("list items must not be empty")
        if len({value.casefold() for value in normalized}) != len(normalized):
            raise ValueError("list items must be unique")
        return normalized

    @field_validator("required_hashtags")
    @classmethod
    def hashtags_start_with_hash(cls, values: list[str]) -> list[str]:
        if any(not value.startswith("#") for value in values):
            raise ValueError("every required hashtag must start with '#'")
        return values

    @model_validator(mode="after")
    def validate_routing_and_rubric(self) -> "AccountPolicy":
        if sum(self.rubric.values()) != 100:
            raise ValueError("rubric weights must total 100")
        if any(weight < 0 or weight > 100 for weight in self.rubric.values()):
            raise ValueError("rubric weights must be between 0 and 100")

        required_roles = {"research", "copywriter", "critic"}
        actual_roles = set(self.model_route)
        if actual_roles != required_roles:
            missing = sorted(required_roles - actual_roles)
            extra = sorted(actual_roles - required_roles)
            details = []
            if missing:
                details.append(f"missing roles: {', '.join(missing)}")
            if extra:
                details.append(f"unknown roles: {', '.join(extra)}")
            raise ValueError("model route must define exactly research/copywriter/critic (" + "; ".join(details) + ")")
        if any(not provider.strip() for provider in self.model_route.values()):
            raise ValueError("model route providers must not be empty")
        if self.model_route["copywriter"].casefold() == self.model_route["critic"].casefold():
            raise ValueError("copywriter and critic must use different providers")
        return self


class PolicyParseError(ValueError):
    """Actionable, file-and-section-specific Markdown policy error."""

    def __init__(
        self,
        path: Path,
        message: str,
        *,
        section: str | None = None,
        line: int | None = None,
    ) -> None:
        self.path = path
        self.section = section
        self.line = line
        location = str(path)
        if section:
            location += f" [section: {section}]"
        if line is not None:
            location += f" [line: {line}]"
        super().__init__(f"{location}: {message}")


def _heading_name(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().casefold())


def _parse_sections(path: Path, text: str) -> dict[str, list[tuple[int, str]]]:
    sections: dict[str, list[tuple[int, str]]] = {}
    current: str | None = None
    allowed = _REQUIRED_SECTIONS | _OPTIONAL_SECTIONS

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        stripped = raw_line.strip()
        if stripped.startswith("## "):
            current = _heading_name(stripped[3:])
            if current not in allowed:
                raise PolicyParseError(
                    path,
                    "unknown section; follow docs/policy_spec.md",
                    section=stripped[3:].strip(),
                    line=line_number,
                )
            if current in sections:
                raise PolicyParseError(
                    path,
                    "section is declared more than once",
                    section=stripped[3:].strip(),
                    line=line_number,
                )
            sections[current] = []
            continue
        if not stripped or stripped.startswith("<!--") or stripped.startswith("# "):
            continue
        if stripped.startswith("###"):
            raise PolicyParseError(path, "nested headings are not supported", line=line_number)
        if current is None:
            raise PolicyParseError(
                path,
                "content must appear under a level-two section",
                line=line_number,
            )
        sections[current].append((line_number, stripped))

    missing = sorted(_REQUIRED_SECTIONS - set(sections))
    if missing:
        formatted = ", ".join(f"## {name.title()}" for name in missing)
        raise PolicyParseError(path, f"missing required section(s): {formatted}")
    return sections


def _scalar(path: Path, name: str, values: list[tuple[int, str]]) -> str:
    if not values:
        raise PolicyParseError(path, "section must not be empty", section=name.title())
    if any(value.startswith("-") for _, value in values):
        raise PolicyParseError(
            path,
            "expected plain text, not a bullet list",
            section=name.title(),
            line=values[0][0],
        )
    return " ".join(value for _, value in values).strip()


def _bullets(path: Path, name: str, values: list[tuple[int, str]], *, allow_empty: bool = False) -> list[str]:
    if not values and allow_empty:
        return []
    if not values:
        raise PolicyParseError(path, "section must contain at least one bullet", section=name.title())
    result: list[str] = []
    for line, value in values:
        if not value.startswith("- ") or not value[2:].strip():
            raise PolicyParseError(
                path,
                "each item must use '- value' Markdown syntax",
                section=name.title(),
                line=line,
            )
        result.append(value[2:].strip())
    return result


def _key_values(path: Path, name: str, values: list[tuple[int, str]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for line, item in zip((line for line, _ in values), _bullets(path, name, values)):
        key, separator, value = item.partition(":")
        normalized_key = key.strip().casefold().replace(" ", "_")
        if not separator or not normalized_key or not value.strip():
            raise PolicyParseError(
                path,
                "each item must use '- key: value' syntax",
                section=name.title(),
                line=line,
            )
        if normalized_key in result:
            raise PolicyParseError(
                path,
                f"duplicate key '{normalized_key}'",
                section=name.title(),
                line=line,
            )
        result[normalized_key] = value.strip()
    return result


def _integer(path: Path, name: str, values: list[tuple[int, str]]) -> int:
    raw = _scalar(path, name, values)
    try:
        return int(raw)
    except ValueError as exc:
        raise PolicyParseError(path, "expected a whole number", section=name.title()) from exc


def _first_validation_error(exc: ValidationError) -> tuple[str, str]:
    error = exc.errors(include_url=False, include_context=False)[0]
    message = str(error["msg"])
    location = error.get("loc") or ()
    if location:
        section = _FIELD_TO_SECTION.get(str(location[0]), "Policy")
    elif "rubric" in message.casefold():
        section = "Rubric"
    elif "provider" in message.casefold() or "model route" in message.casefold():
        section = "Model Route"
    else:
        section = "Policy"
    return section, message


def parse_policy_text(text: str, *, source: str | Path = "<memory>") -> AccountPolicy:
    path = Path(source)
    sections = _parse_sections(path, text)
    account = _key_values(path, "account", sections["account"])
    expected_account_keys = {"account_id", "spec_version"}
    if set(account) != expected_account_keys:
        missing = sorted(expected_account_keys - set(account))
        extra = sorted(set(account) - expected_account_keys)
        details: list[str] = []
        if missing:
            details.append(f"missing: {', '.join(missing)}")
        if extra:
            details.append(f"unknown: {', '.join(extra)}")
        raise PolicyParseError(path, "; ".join(details), section="Account")

    rubric_raw = _key_values(path, "rubric", sections["rubric"])
    try:
        rubric = {key: int(value) for key, value in rubric_raw.items()}
    except ValueError as exc:
        raise PolicyParseError(path, "rubric weights must be whole numbers", section="Rubric") from exc

    payload = {
        "spec_version": account["spec_version"],
        "account_id": account["account_id"],
        "goal": _scalar(path, "goal", sections["goal"]),
        "audience": _scalar(path, "audience", sections["audience"]),
        "platform": _scalar(path, "platform", sections["platform"]),
        "tone": _scalar(path, "tone", sections["tone"]),
        "language": _scalar(path, "language", sections["language"]),
        "constraints": _bullets(path, "constraints", sections["constraints"]),
        "banned_terms": _bullets(
            path,
            "banned terms",
            sections.get("banned terms", []),
            allow_empty=True,
        ),
        "required_hashtags": _bullets(
            path,
            "required hashtags",
            sections.get("required hashtags", []),
            allow_empty=True,
        ),
        "examples": _bullets(path, "examples", sections["examples"]),
        "rubric": rubric,
        "threshold": _integer(path, "threshold", sections["threshold"]),
        "max_length": _integer(path, "maximum length", sections["maximum length"]),
        "model_route": _key_values(path, "model route", sections["model route"]),
    }
    try:
        return AccountPolicy.model_validate(payload)
    except ValidationError as exc:
        section, message = _first_validation_error(exc)
        raise PolicyParseError(path, message, section=section) from exc


def load_policy(path: str | Path) -> AccountPolicy:
    resolved = Path(path)
    try:
        text = resolved.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise PolicyParseError(resolved, "file does not exist") from exc
    except UnicodeDecodeError as exc:
        raise PolicyParseError(resolved, "file must be UTF-8 encoded") from exc
    except OSError as exc:
        raise PolicyParseError(resolved, "file could not be read") from exc
    return parse_policy_text(text, source=resolved)


def load_policies(paths: Iterable[str | Path]) -> list[AccountPolicy]:
    policies = [load_policy(path) for path in paths]
    seen: set[str] = set()
    for policy in policies:
        if policy.account_id in seen:
            raise ValueError(f"duplicate account_id across policy files: {policy.account_id}")
        seen.add(policy.account_id)
    return policies
