"""Google Gemini structured-output adapter."""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Literal

from google import genai
from google.genai import types

from ..base import ChatMessage, ProviderResponse, SchemaT, StructuredProvider, parse_structured_text
from ..errors import ProviderError, missing_credential, normalize_provider_exception
from ._utils import metadata, sdk_version


class GeminiProvider(StructuredProvider):
    provider_name: Literal["gemini"] = "gemini"

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str = "gemini-3.1-flash-lite",
        client: object | None = None,
        timeout_seconds: float = 45.0,
    ) -> None:
        self.model = model
        self.timeout_seconds = timeout_seconds
        if client is None and not api_key:
            raise missing_credential(self.provider_name, model, "GEMINI_API_KEY")
        self.client = client or genai.Client(api_key=api_key)

    def generate(
        self,
        *,
        messages: Sequence[ChatMessage],
        response_model: type[SchemaT],
        role: Literal["research", "copywriter", "critic"],
        prompt_version: str,
    ) -> ProviderResponse[SchemaT]:
        system_instruction = "\n\n".join(
            message.content for message in messages if message.role in {"system", "developer"}
        )
        contents = "\n\n".join(
            f"{message.role.upper()}: {message.content}"
            for message in messages
            if message.role not in {"system", "developer"}
        )
        started = time.perf_counter()
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json",
                    response_json_schema=response_model.model_json_schema(),
                    temperature=0.2,
                    max_output_tokens=1400,
                    http_options=types.HttpOptions(timeout=int(self.timeout_seconds * 1000)),
                ),
            )
            parsed = parse_structured_text(
                response.text,
                response_model,
                provider=self.provider_name,
                model=self.model,
            )
        except ProviderError:
            raise
        except Exception as exc:
            raise normalize_provider_exception(exc, provider=self.provider_name, model=self.model) from exc

        usage = getattr(response, "usage_metadata", None)
        latency_ms = round((time.perf_counter() - started) * 1000)
        return ProviderResponse(
            output=parsed,
            metadata=metadata(
                provider=self.provider_name,
                model=self.model,
                role=role,
                prompt_version=prompt_version,
                provider_sdk=sdk_version("google-genai"),
                latency_ms=latency_ms,
                input_tokens=getattr(usage, "prompt_token_count", 0),
                output_tokens=getattr(usage, "candidates_token_count", 0),
                total_tokens=getattr(usage, "total_token_count", 0),
                request_id=getattr(response, "response_id", None),
            ),
        )
