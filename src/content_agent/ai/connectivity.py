"""Safe, non-generation connectivity probes for configured AI providers."""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Literal

import httpx
from pydantic import Field

from .config import DEFAULT_ROUTES, Role
from .models import StrictModel

ProbeStatus = Literal[
    "ready",
    "missing",
    "authentication",
    "permission",
    "rate_limited",
    "network",
    "provider_error",
    "model_unavailable",
]


class ConnectionProbeResult(StrictModel):
    role: Role
    provider: str
    model: str
    status: ProbeStatus
    message: str = Field(min_length=1)
    http_status: int | None = None
    latency_ms: int = Field(default=0, ge=0)

    @property
    def ready(self) -> bool:
        return self.status == "ready"


def _probe_request(
    role: Role,
    credential: str,
    *,
    client: httpx.Client,
) -> httpx.Response:
    route = DEFAULT_ROUTES[role]
    if route.provider == "gemini":
        return client.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            params={"key": credential, "pageSize": 1000},
        )
    headers = {"Authorization": f"Bearer {credential}"}
    if route.provider == "groq":
        return client.get(
            "https://api.groq.com/openai/v1/models",
            headers=headers,
        )
    if route.provider == "github_models":
        headers.update(
            {
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2026-03-10",
            }
        )
        return client.get(
            "https://models.github.ai/catalog/models",
            headers=headers,
        )
    raise ValueError(f"Unsupported provider for connectivity probe: {route.provider}")


def _available_model_ids(provider: str, response: httpx.Response) -> set[str]:
    payload = response.json()
    if provider == "gemini":
        return {
            str(item.get("name", "")).removeprefix("models/")
            for item in payload.get("models", [])
            if isinstance(item, dict)
        }
    if provider == "groq":
        return {str(item.get("id", "")) for item in payload.get("data", []) if isinstance(item, dict)}
    if provider == "github_models" and isinstance(payload, list):
        return {str(item.get("id", "")) for item in payload if isinstance(item, dict)}
    return set()


def probe_role_connection(
    role: Role | str,
    *,
    env: Mapping[str, str],
    client: httpx.Client | None = None,
    timeout_seconds: float = 8.0,
) -> ConnectionProbeResult:
    """Validate credential, endpoint, and configured model without generation."""

    normalized_role = role if isinstance(role, Role) else Role(role)
    route = DEFAULT_ROUTES[normalized_role]
    model = route.selected_model(env)
    credential = env.get(route.credential_env, "").strip()
    if not credential:
        return ConnectionProbeResult(
            role=normalized_role,
            provider=route.provider,
            model=model,
            status="missing",
            message=f"Missing {route.credential_env}.",
        )

    owned_client = client is None
    http_client = client or httpx.Client(
        timeout=timeout_seconds,
        follow_redirects=True,
        trust_env=True,
    )
    started = time.perf_counter()
    try:
        response = _probe_request(
            normalized_role,
            credential,
            client=http_client,
        )
        latency_ms = round((time.perf_counter() - started) * 1000)
    except httpx.RequestError:
        return ConnectionProbeResult(
            role=normalized_role,
            provider=route.provider,
            model=model,
            status="network",
            message="Provider endpoint is unreachable from this app process.",
            latency_ms=round((time.perf_counter() - started) * 1000),
        )
    finally:
        if owned_client:
            http_client.close()

    if response.status_code == 401:
        status, message = "authentication", "Credential was rejected."
    elif response.status_code == 403:
        status, message = "permission", "Credential lacks provider/model permission."
    elif response.status_code == 429:
        status, message = "rate_limited", "Provider rate limit is active; retry later."
    elif response.status_code >= 500:
        status, message = "provider_error", "Provider service is temporarily unavailable."
    elif response.status_code >= 400:
        status, message = "provider_error", f"Provider returned HTTP {response.status_code}."
    else:
        try:
            available = _available_model_ids(route.provider, response)
        except (TypeError, ValueError):
            available = set()
        if available and model not in available:
            status = "model_unavailable"
            message = f"Connected, but configured model '{model}' is not available."
        else:
            status = "ready"
            message = "Credential, endpoint, and configured model are ready."
    return ConnectionProbeResult(
        role=normalized_role,
        provider=route.provider,
        model=model,
        status=status,
        message=message,
        http_status=response.status_code,
        latency_ms=latency_ms,
    )


def probe_all_connections(
    *,
    env: Mapping[str, str],
    timeout_seconds: float = 8.0,
) -> list[ConnectionProbeResult]:
    """Probe every required route while keeping failures isolated."""

    with httpx.Client(
        timeout=timeout_seconds,
        follow_redirects=True,
        trust_env=True,
    ) as client:
        return [
            probe_role_connection(role, env=env, client=client, timeout_seconds=timeout_seconds)
            for role in Role
        ]
