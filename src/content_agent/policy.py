"""Versioned Markdown account-policy contract and parser for POL-01."""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError, field_validator, model_validator

from .ai.models import StrictModel

POLICY_SPEC_VERSION = "0.2"
SUPPORTED_POLICY_VERSIONS = {"0.1", POLICY_SPEC_VERSION}
SUPPORTED_PROVIDERS = {"gemini", "groq", "github_models"}

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
_OPTIONAL_SECTIONS = {"banned terms", "required hashtags", "publishing"}
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
    "model_overrides": "Model Route",
    "publishing": "Publishing",
}


class PublishingConfig(StrictModel):
    """Non-secret delivery settings controlled by an account policy."""

    adapter: Literal["mock", "facebook_page", "threads"] = "mock"
    target_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )
    credential_ref: str | None = Field(
        default=None,
        min_length=3,
        max_length=128,
        pattern=r"^[A-Z][A-Z0-9_]+$",
    )
    approval_required: bool = False
    topic_tag: str | None = Field(default=None, min_length=1, max_length=50)
    topic_tag_candidates: list[str] = Field(default_factory=list, max_length=5)
    trend_search: bool = False

    @staticmethod
    def _clean_topic_tag(value: str) -> str:
        normalized = value.strip().removeprefix("#").strip()
        if not normalized:
            raise ValueError("Threads topic tags must not be empty")
        if len(normalized) > 50:
            raise ValueError("Threads topic tags must contain at most 50 characters")
        if any(character in normalized for character in ".&\r\n"):
            raise ValueError("Threads topic tags must not contain '.', '&', or newlines")
        return normalized

    @field_validator("topic_tag", mode="before")
    @classmethod
    def normalize_topic_tag(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("Threads topic_tag must be text")
        return cls._clean_topic_tag(value)

    @field_validator("topic_tag_candidates")
    @classmethod
    def normalize_topic_tag_candidates(cls, values: list[str]) -> list[str]:
        normalized = [cls._clean_topic_tag(value) for value in values]
        if len({value.casefold() for value in normalized}) != len(normalized):
            raise ValueError("Threads topic_tag_candidates must be unique")
        return normalized

    @model_validator(mode="after")
    def validate_delivery_target(self) -> PublishingConfig:
        if self.adapter == "mock":
            if (
                self.target_id
                or self.credential_ref
                or self.topic_tag
                or self.topic_tag_candidates
                or self.trend_search
            ):
                raise ValueError(
                    "mock publishing must not define target, credential, or Threads tag settings"
                )
            return self
        if not self.target_id:
            raise ValueError(f"{self.adapter} publishing requires target_id")
        if not self.credential_ref:
            raise ValueError(f"{self.adapter} publishing requires credential_ref")
        if self.adapter != "threads" and (self.topic_tag or self.topic_tag_candidates or self.trend_search):
            raise ValueError("topic tag settings are supported only by the threads adapter")
        combined_tags = {value.casefold() for value in self.topic_tag_candidates}
        if self.topic_tag:
            combined_tags.add(self.topic_tag.casefold())
        if len(combined_tags) > 5:
            raise ValueError("Threads publishing supports at most five total topic tags")
        if self.trend_search and not (self.topic_tag_candidates or self.topic_tag):
            raise ValueError("trend_search requires topic_tag or topic_tag_candidates")
        return self


class AccountPolicy(StrictModel):
    """Canonical versioned policy shared by orchestration and publishing."""

    spec_version: str = Field(pattern=r"^0\.(?:1|2)$")
    account_id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    active: bool = True
    goal: str = Field(min_length=10)
    audience: str = Field(min_length=3)
    platform: str = Field(min_length=1)
    tone: str = Field(min_length=3)
    language: str = Field(min_length=2)
    constraints: list[str] = Field(min_length=1)
    banned_terms: list[str] = Field(default_factory=list)
    required_hashtags: list[str] = Field(default_factory=list)
    examples: list[str] = Field(min_length=2, max_length=3)
    rubric: dict[str, int] = Field(min_length=1)
    threshold: int = Field(ge=0, le=100)
    max_length: int = Field(ge=1, le=10_000)
    model_route: dict[str, str]
    model_overrides: dict[str, str] = Field(default_factory=dict)
    publishing: PublishingConfig = Field(default_factory=PublishingConfig)

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
    def validate_routing_and_rubric(self) -> AccountPolicy:
        if self.spec_version not in SUPPORTED_POLICY_VERSIONS:
            raise ValueError(f"unsupported policy spec_version: {self.spec_version}")
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
            raise ValueError(
                "model route must define exactly research/copywriter/critic (" + "; ".join(details) + ")"
            )
        if any(not provider.strip() for provider in self.model_route.values()):
            raise ValueError("model route providers must not be empty")
        unknown_providers = set(self.model_route.values()) - SUPPORTED_PROVIDERS
        if unknown_providers:
            raise ValueError("unsupported model route provider(s): " + ", ".join(sorted(unknown_providers)))
        unknown_override_roles = set(self.model_overrides) - required_roles
        if unknown_override_roles:
            raise ValueError(
                "model overrides contain unknown role(s): " + ", ".join(sorted(unknown_override_roles))
            )
        if any(not model.strip() for model in self.model_overrides.values()):
            raise ValueError("model override values must not be empty")
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


def _boolean(path: Path, name: str, raw: str, *, section: str) -> bool:
    normalized = raw.strip().casefold()
    if normalized in {"true", "yes", "1"}:
        return True
    if normalized in {"false", "no", "0"}:
        return False
    raise PolicyParseError(
        path,
        f"{name} must be true or false",
        section=section,
    )


def _parse_model_route(
    path: Path,
    values: list[tuple[int, str]],
) -> tuple[dict[str, str], dict[str, str]]:
    raw_routes = _key_values(path, "model route", values)
    providers: dict[str, str] = {}
    models: dict[str, str] = {}
    for role, raw_value in raw_routes.items():
        provider, separator, model = raw_value.partition("@")
        normalized_provider = provider.strip().casefold()
        if not normalized_provider:
            raise PolicyParseError(
                path,
                f"provider for role '{role}' must not be empty",
                section="Model Route",
            )
        providers[role] = normalized_provider
        if separator:
            normalized_model = model.strip()
            if not normalized_model:
                raise PolicyParseError(
                    path,
                    f"model override for role '{role}' must not be empty",
                    section="Model Route",
                )
            models[role] = normalized_model
    return providers, models


def _parse_publishing(
    path: Path,
    values: list[tuple[int, str]],
) -> PublishingConfig:
    if not values:
        return PublishingConfig()
    raw = _key_values(path, "publishing", values)
    allowed = {
        "adapter",
        "target_id",
        "credential_ref",
        "approval_required",
        "topic_tag",
        "topic_tag_candidates",
        "trend_search",
    }
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise PolicyParseError(
            path,
            f"unknown publishing key(s): {', '.join(unknown)}",
            section="Publishing",
        )
    payload: dict[str, object] = {
        "adapter": raw.get("adapter", "mock").strip().casefold(),
    }
    if "target_id" in raw:
        payload["target_id"] = raw["target_id"]
    if "credential_ref" in raw:
        payload["credential_ref"] = raw["credential_ref"]
    if "approval_required" in raw:
        payload["approval_required"] = _boolean(
            path,
            "approval_required",
            raw["approval_required"],
            section="Publishing",
        )
    if "topic_tag" in raw:
        payload["topic_tag"] = raw["topic_tag"]
    if "topic_tag_candidates" in raw:
        payload["topic_tag_candidates"] = [
            candidate.strip() for candidate in raw["topic_tag_candidates"].split("|")
        ]
    if "trend_search" in raw:
        payload["trend_search"] = _boolean(
            path,
            "trend_search",
            raw["trend_search"],
            section="Publishing",
        )
    try:
        return PublishingConfig.model_validate(payload)
    except ValidationError as exc:
        message = str(exc.errors(include_url=False, include_context=False)[0]["msg"])
        raise PolicyParseError(path, message, section="Publishing") from exc


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
    required_account_keys = {"account_id", "spec_version"}
    allowed_account_keys = required_account_keys | {"active"}
    if not required_account_keys.issubset(account) or set(account) - allowed_account_keys:
        missing = sorted(required_account_keys - set(account))
        extra = sorted(set(account) - allowed_account_keys)
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

    model_route, model_overrides = _parse_model_route(path, sections["model route"])
    payload = {
        "spec_version": account["spec_version"],
        "account_id": account["account_id"],
        "active": _boolean(
            path,
            "active",
            account.get("active", "true"),
            section="Account",
        ),
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
        "model_route": model_route,
        "model_overrides": model_overrides,
        "publishing": _parse_publishing(path, sections.get("publishing", [])),
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
