"""Validate Day 1 provider routes with schema-checked, secret-safe samples."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from dotenv import load_dotenv

from content_agent.ai.agents import CopywriterAgent, ResearchAgent
from content_agent.ai.base import ChatMessage
from content_agent.ai.config import DEFAULT_ROUTES, Role
from content_agent.ai.errors import ProviderError
from content_agent.ai.models import (
    CriticPayload,
    CriticResult,
    DraftPost,
    PolicyContext,
    ResearchBrief,
)
from content_agent.ai.prompts import CRITIC_PROBE_PROMPT_VERSION, build_critic_probe_messages
from content_agent.ai.registry import create_role_provider

FIXTURES = ROOT / "tests" / "fixtures"
DEFAULT_OUTPUT = ROOT / "artifacts" / "provider_spike_results.json"
DEFAULT_SMOKE_OUTPUT = ROOT / "artifacts" / "github_models_smoke.json"


class GitHubSmokePayload(BaseModel):
    """Small connection-check schema retained from the original smoke script."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    caption: str = Field(min_length=1)
    hashtags: list[str]
    cta: str = Field(min_length=1)


def load_fixture(name: str, model: type[Any]) -> Any:
    with (FIXTURES / name).open("r", encoding="utf-8") as handle:
        return model.model_validate(json.load(handle))


def redact_sample(value: Any) -> Any:
    """The contracts contain no credentials; keep this guard for future fields."""

    secret_words = {"api_key", "token", "secret", "authorization"}
    if isinstance(value, dict):
        return {
            key: "<redacted>" if key.lower() in secret_words else redact_sample(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_sample(item) for item in value]
    return value


def run_probe(role: Role, fallback_index: int | None = None) -> dict[str, Any]:
    route = DEFAULT_ROUTES[role]
    provider = create_role_provider(role, fallback_index=fallback_index)
    policy = load_fixture("policy_valid.json", PolicyContext)

    if role is Role.RESEARCH:
        output = ResearchAgent(provider).run(
            topic="How small teams can use AI responsibly for social content",
            policy=policy,
        )
    elif role is Role.COPYWRITER:
        research = load_fixture("research_brief_valid.json", ResearchBrief)
        output = CopywriterAgent(provider).run(research=research, policy=policy)
    else:
        draft = load_fixture("draft_post_valid.json", DraftPost)
        response = provider.generate(
            messages=build_critic_probe_messages(draft, policy),
            response_model=CriticPayload,
            role="critic",
            prompt_version=CRITIC_PROBE_PROMPT_VERSION,
        )
        output = CriticResult(
            **response.output.model_dump(),
            draft_id=draft.draft_id,
            account_id=policy.account_id,
            metadata=response.metadata,
        )

    return {
        "status": "passed",
        "role": role.value,
        "provider": route.provider,
        "model": provider.model,
        "schema": type(output).__name__,
        "metadata": output.metadata.model_dump(mode="json"),
        "sample": redact_sample(output.model_dump(mode="json")),
    }


def run_github_smoke() -> dict[str, Any]:
    """Run the former standalone GitHub smoke test through the shared adapter."""

    route = DEFAULT_ROUTES[Role.CRITIC]
    provider = create_role_provider(Role.CRITIC)
    response = provider.generate(
        messages=[
            ChatMessage(
                role="system",
                content="You are a social media copywriter. Return valid JSON only.",
            ),
            ChatMessage(
                role="user",
                content=(
                    "Write a short launch post for a productivity app. "
                    "Return JSON with caption, hashtags as an array, and cta."
                ),
            ),
        ],
        response_model=GitHubSmokePayload,
        role="critic",
        prompt_version="github-models-smoke-v1",
    )
    return {
        "status": "passed",
        "role": "github_smoke",
        "provider": route.provider,
        "model": provider.model,
        "route": "primary",
        "schema": GitHubSmokePayload.__name__,
        "metadata": response.metadata.model_dump(mode="json"),
        "sample": redact_sample(response.output.model_dump(mode="json")),
    }


def github_smoke_rows() -> list[dict[str, Any]]:
    try:
        return [run_github_smoke()]
    except ProviderError as exc:
        return [
            {
                "status": "failed",
                "role": "github_smoke",
                "provider": DEFAULT_ROUTES[Role.CRITIC].provider,
                "model": DEFAULT_ROUTES[Role.CRITIC].selected_model(),
                "route": "primary",
                "error": exc.as_dict(),
            }
        ]


def selected_roles(provider_arg: str) -> list[Role]:
    if provider_arg == "all":
        return list(Role)
    by_provider = {route.provider: role for role, route in DEFAULT_ROUTES.items()}
    return [by_provider[provider_arg]]


def dry_run_rows(roles: list[Role], include_fallbacks: bool) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for role in roles:
        route = DEFAULT_ROUTES[role]
        models = [route.selected_model()]
        if include_fallbacks:
            models.extend(route.fallback_models)
        for index, model in enumerate(models):
            rows.append(
                {
                    "status": "configured",
                    "role": role.value,
                    "provider": route.provider,
                    "model": model,
                    "route": "primary" if index == 0 else f"fallback_{index}",
                    "credential_env": route.credential_env,
                    "credential_present": bool(os.getenv(route.credential_env)),
                    "free_tier_note": route.free_tier_note,
                    "lifecycle_note": route.lifecycle_note,
                }
            )
    return rows


def live_rows(roles: list[Role], include_fallbacks: bool) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for role in roles:
        attempts: list[int | None] = [None]
        if include_fallbacks:
            attempts.extend(range(len(DEFAULT_ROUTES[role].fallback_models)))
        for fallback_index in attempts:
            try:
                row = run_probe(role, fallback_index=fallback_index)
                row["route"] = "primary" if fallback_index is None else f"fallback_{fallback_index + 1}"
            except ProviderError as exc:
                row = {
                    "status": "failed",
                    "role": role.value,
                    "provider": DEFAULT_ROUTES[role].provider,
                    "model": (
                        DEFAULT_ROUTES[role].selected_model()
                        if fallback_index is None
                        else DEFAULT_ROUTES[role].fallback_models[fallback_index]
                    ),
                    "route": "primary" if fallback_index is None else f"fallback_{fallback_index + 1}",
                    "error": exc.as_dict(),
                }
            rows.append(row)
    return rows


def write_artifact(path: Path, *, mode: str, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "free_tier_expected": True,
        "results": rows,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def print_rows(rows: list[dict[str, Any]]) -> None:
    print(f"{'ROLE':<12} {'PROVIDER':<16} {'ROUTE':<12} {'STATUS':<12} MODEL")
    for row in rows:
        print(
            f"{row['role']:<12} {row['provider']:<16} {row['route']:<12} "
            f"{row['status']:<12} {row['model']}"
        )
        if "error" in row:
            print(f"  error={row['error']['code']}: {row['error']['message']}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--provider",
        choices=["all", "gemini", "groq", "github_models"],
        default="all",
        help="Provider route to validate (default: all).",
    )
    parser.add_argument("--dry-run", action="store_true", help="Inspect routes without calling any API.")
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Run the lightweight GitHub-only connection/JSON smoke test.",
    )
    parser.add_argument(
        "--include-fallbacks",
        action="store_true",
        help="Also call fallback models; consumes additional free-tier requests.",
    )
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    if args.smoke and args.provider != "github_models":
        parser.error("--smoke requires --provider github_models")
    if args.smoke and args.dry_run:
        parser.error("--smoke cannot be combined with --dry-run")
    if args.smoke and args.include_fallbacks:
        parser.error("--smoke cannot be combined with --include-fallbacks")
    return args


def main() -> int:
    args = parse_args()
    load_dotenv(ROOT / ".env", override=True)
    if args.smoke:
        rows = github_smoke_rows()
        mode = "github-smoke"
        output = args.output or DEFAULT_SMOKE_OUTPUT
    else:
        roles = selected_roles(args.provider)
        rows = (
            dry_run_rows(roles, args.include_fallbacks)
            if args.dry_run
            else live_rows(roles, args.include_fallbacks)
        )
        mode = "dry-run" if args.dry_run else "live"
        output = args.output or DEFAULT_OUTPUT
    write_artifact(output, mode=mode, rows=rows)
    print_rows(rows)
    print(f"Artifact: {output}")
    return 0 if args.dry_run or all(row["status"] == "passed" for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
