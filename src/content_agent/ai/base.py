"""Provider adapter contract and common structured-output parsing."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ValidationError

from .errors import ErrorCode, ProviderError
from .models import GenerationMetadata

SchemaT = TypeVar("SchemaT", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: Literal["system", "developer", "user", "assistant"]
    content: str


@dataclass(frozen=True, slots=True)
class ProviderResponse(Generic[SchemaT]):
    output: SchemaT
    metadata: GenerationMetadata


class StructuredProvider(ABC):
    provider_name: Literal["gemini", "groq", "github_models"]
    model: str

    @abstractmethod
    def generate(
        self,
        *,
        messages: Sequence[ChatMessage],
        response_model: type[SchemaT],
        role: Literal["research", "copywriter", "critic"],
        prompt_version: str,
    ) -> ProviderResponse[SchemaT]:
        """Return an output validated against response_model."""


def parse_structured_text(
    text: str,
    response_model: type[SchemaT],
    *,
    provider: str,
    model: str,
) -> SchemaT:
    """Parse JSON defensively and convert failures into safe error codes."""

    candidate = (text or "").strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        candidate = "\n".join(lines).strip()

    try:
        payload = json.loads(candidate)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ProviderError(
            ErrorCode.MALFORMED_RESPONSE,
            "Provider returned malformed JSON.",
            provider=provider,
            model=model,
            retryable=True,
        ) from exc

    try:
        return response_model.model_validate(payload)
    except ValidationError as exc:
        raise ProviderError(
            ErrorCode.SCHEMA_VALIDATION,
            f"Provider JSON failed {response_model.__name__} validation.",
            provider=provider,
            model=model,
            retryable=True,
        ) from exc
