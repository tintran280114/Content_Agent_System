"""Provider factory for primary and explicitly requested fallback models."""

from __future__ import annotations

import os
from collections.abc import Mapping

from .base import StructuredProvider
from .config import DEFAULT_ROUTES, Role
from .providers import GeminiProvider, GitHubModelsProvider, GroqProvider

PROVIDER_ROUTES = {route.provider: route for route in DEFAULT_ROUTES.values()}


def create_role_provider(
    role: Role | str,
    *,
    provider: str | None = None,
    model: str | None = None,
    fallback_index: int | None = None,
    env: Mapping[str, str] | None = None,
) -> StructuredProvider:
    normalized_role = role if isinstance(role, Role) else Role(role)
    default_route = DEFAULT_ROUTES[normalized_role]
    provider_name = (provider or default_route.provider).strip().casefold()
    try:
        route = PROVIDER_ROUTES[provider_name]
    except KeyError as exc:
        raise ValueError(f"Unsupported provider: {provider_name}") from exc
    source = os.environ if env is None else env

    if model is not None and fallback_index is not None:
        raise ValueError("model and fallback_index are mutually exclusive")
    if model is not None:
        selected_model = model.strip()
        if not selected_model:
            raise ValueError("model override must not be empty")
    elif fallback_index is None:
        selected_model = source.get(route.model_env, route.primary_model)
    else:
        try:
            selected_model = route.fallback_models[fallback_index]
        except IndexError as exc:
            raise ValueError(f"No fallback {fallback_index} for role {normalized_role.value}") from exc

    api_key = source.get(route.credential_env)
    if provider_name == "gemini":
        return GeminiProvider(api_key=api_key, model=selected_model)
    if provider_name == "groq":
        return GroqProvider(api_key=api_key, model=selected_model)
    if provider_name == "github_models":
        return GitHubModelsProvider(api_key=api_key, model=selected_model)
    raise AssertionError(f"validated provider was not constructed: {provider_name}")
