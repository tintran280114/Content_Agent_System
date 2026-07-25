"""Run the live Gemini Research -> Groq Copywriter Day 1 handoff."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from dotenv import load_dotenv

from content_agent.ai.agents import run_research_copywriter
from content_agent.ai.config import Role
from content_agent.ai.models import PolicyContext
from content_agent.ai.registry import create_role_provider


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--topic",
        default="How small teams can use AI responsibly for social content",
    )
    parser.add_argument(
        "--policy",
        type=Path,
        default=ROOT / "tests" / "fixtures" / "policy_valid.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "artifacts" / "ai_day1_demo.json",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_dotenv(ROOT / ".env", override=True)
    policy = PolicyContext.model_validate_json(args.policy.read_text(encoding="utf-8"))
    result = run_research_copywriter(
        topic=args.topic,
        policy=policy,
        research_provider=create_role_provider(Role.RESEARCH),
        copywriter_provider=create_role_provider(Role.COPYWRITER),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    print(f"Account: {result.draft.account_id}")
    print(f"Research: {result.research.metadata.provider}/{result.research.metadata.model}")
    print(f"Copywriter: {result.draft.metadata.provider}/{result.draft.metadata.model}")
    print(f"Draft: {result.draft.content}")
    print(f"Artifact: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
