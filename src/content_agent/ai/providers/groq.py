"""Groq Free Plan structured-output adapter."""

from __future__ import annotations

import json
import time
from typing import Literal, Sequence

from groq import Groq

from ..base import ChatMessage, ProviderResponse, SchemaT, StructuredProvider, parse_structured_text
from ..errors import ProviderError, missing_credential, normalize_provider_exception
from ._utils import metadata, sdk_version


class GroqProvider(StructuredProvider):
    provider_name: Literal["groq"] = "groq"

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str = "openai/gpt-oss-120b",
        client: object | None = None,
        timeout_seconds: float = 45.0,
    ) -> None:
        self.model = model
        if client is None and not api_key:
            raise missing_credential(self.provider_name, model, "GROQ_API_KEY")
        self.client = client or Groq(api_key=api_key, timeout=timeout_seconds)

    def generate(
        self,
        *,
        messages: Sequence[ChatMessage],
        response_model: type[SchemaT],
        role: Literal["research", "copywriter", "critic"],
        prompt_version: str,
    ) -> ProviderResponse[SchemaT]:
        request_messages = [
            {"role": message.role, "content": message.content}
            for message in messages
        ]
        request_messages[-1]["content"] += (
            "\n\nThe JSON object must validate against this schema:\n"
            + json.dumps(response_model.model_json_schema(), ensure_ascii=False)
        )
        started = time.perf_counter()
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=request_messages,
                response_format={"type": "json_object"},
                temperature=0.2,
                max_completion_tokens=1400,
            )
            text = response.choices[0].message.content
            parsed = parse_structured_text(
                text,
                response_model,
                provider=self.provider_name,
                model=self.model,
            )
        except ProviderError:
            raise
        except Exception as exc:
            raise normalize_provider_exception(exc, provider=self.provider_name, model=self.model) from exc

        usage = getattr(response, "usage", None)
        latency_ms = round((time.perf_counter() - started) * 1000)
        return ProviderResponse(
            output=parsed,
            metadata=metadata(
                provider=self.provider_name,
                model=self.model,
                role=role,
                prompt_version=prompt_version,
                provider_sdk=sdk_version("groq"),
                latency_ms=latency_ms,
                input_tokens=getattr(usage, "prompt_tokens", 0),
                output_tokens=getattr(usage, "completion_tokens", 0),
                total_tokens=getattr(usage, "total_tokens", 0),
                request_id=getattr(response, "id", None),
            ),
        )
