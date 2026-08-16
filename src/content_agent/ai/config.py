"""Pinned free-tier routes for the Wednesday MVP."""

from __future__ import annotations

import os
from collections.abc import Mapping
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Role(StrEnum):
    RESEARCH = "research"
    COPYWRITER = "copywriter"
    CRITIC = "critic"


class ModelRoute(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: Role
    provider: str
    credential_env: str
    model_env: str
    primary_model: str
    fallback_models: tuple[str, ...] = ()
    free_tier_note: str = Field(min_length=1)
    lifecycle_note: str | None = None

    def selected_model(self, env: Mapping[str, str] | None = None) -> str:
        source = os.environ if env is None else env
        return source.get(self.model_env, self.primary_model)


DEFAULT_ROUTES: dict[Role, ModelRoute] = {
    Role.RESEARCH: ModelRoute(
        role=Role.RESEARCH,
        provider="gemini",
        credential_env="GEMINI_API_KEY",
        model_env="GEMINI_MODEL",
        primary_model="gemini-3.1-flash-lite",
        fallback_models=("gemini-3.5-flash",),
        free_tier_note="Gemini Developer API free tier; no search grounding in the default prompt.",
    ),
    Role.COPYWRITER: ModelRoute(
        role=Role.COPYWRITER,
        provider="groq",
        credential_env="GROQ_API_KEY",
        model_env="GROQ_MODEL",
        primary_model="openai/gpt-oss-120b",
        fallback_models=("qwen/qwen3.6-27b",),
        free_tier_note="Groq Free Plan, subject to the organization Limits page.",
        lifecycle_note=(
            "Migrated from llama-3.3-70b-versatile before its free/developer shutdown on 2026-08-16."
        ),
    ),
    Role.CRITIC: ModelRoute(
        role=Role.CRITIC,
        provider="groq",
        credential_env="GROQ_API_KEY",
        model_env="GROQ_CRITIC_MODEL",
        primary_model="openai/gpt-oss-20b",
        fallback_models=("qwen/qwen3.6-27b",),
        free_tier_note="Groq Free Plan, subject to the organization Limits page.",
        lifecycle_note="Migrated from GitHub Models during its 2026 retirement brownout.",
    ),
}
