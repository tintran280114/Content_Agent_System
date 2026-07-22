"""Run the CLI-first social-content batch pipeline."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from dotenv import load_dotenv

from content_agent.orchestrator import Day1Orchestrator, Day1RunError
from content_agent.full_pipeline import FullPipelineError, FullPipelineOrchestrator
from content_agent.platform import SQLiteRunStore
from content_agent.policy import PolicyParseError, load_policies

DEFAULT_TOPIC = "How small teams can use AI responsibly for social content"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument(
        "--account",
        metavar="SLUG_OR_PATH",
        help="Account slug from accounts/ or an explicit Markdown policy path.",
    )
    action.add_argument(
        "--all",
        action="store_true",
        help="Run every valid account policy in accounts/ as separate traceable runs.",
    )
    action.add_argument(
        "--list-accounts",
        action="store_true",
        help="Validate and list available account policies without calling a provider.",
    )
    parser.add_argument("--topic", default=DEFAULT_TOPIC, help="Topic supplied to the Research Agent.")
    parser.add_argument(
        "--pipeline",
        choices=("draft", "full"),
        help=(
            "draft preserves the Day 1 slice; full adds Critic, rewrites, review, and mock publish. "
            "Default: draft for --account, full for --all."
        ),
    )
    parser.add_argument(
        "--accounts-dir",
        type=Path,
        default=ROOT / "accounts",
        help="Directory used to resolve account slugs (default: accounts/).",
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=ROOT / "artifacts" / "day1.sqlite3",
        help="SQLite database path (default: artifacts/day1.sqlite3).",
    )
    return parser


def _policy_files(accounts_dir: Path) -> list[Path]:
    return sorted(path for path in accounts_dir.glob("*.md") if path.name != "template.md")


def resolve_policy_path(value: str, accounts_dir: Path) -> Path:
    candidate = Path(value)
    if candidate.is_absolute() or len(candidate.parts) > 1:
        return candidate
    filename = candidate.name if candidate.suffix.casefold() == ".md" else f"{candidate.name}.md"
    return accounts_dir / filename


def _print_result(result, *, database: Path, pipeline: str) -> None:
    print(f"run_id={result.run_id}")
    print(f"state=completed")
    print(f"account={result.policy.account_id}")
    print(f"research_brief_id={result.research.brief_id}")
    print(f"draft_post_id={result.draft.draft_id}")
    if pipeline == "full":
        print(f"workflow_state={result.workflow_state.value}")
        print(f"rewrite_count={result.rewrite_count}")
        print(f"critic_score={result.critic.score if result.critic else 'unavailable'}")
    print(f"database={database}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_dotenv(ROOT / ".env", override=False)
    pipeline = args.pipeline or ("full" if args.all else "draft")

    try:
        if args.list_accounts:
            policies = load_policies(_policy_files(args.accounts_dir))
            for policy in policies:
                print(f"{policy.account_id}\t{policy.platform}\tmax_length={policy.max_length}")
            return 0

        store = SQLiteRunStore(args.database)
        policy_paths = _policy_files(args.accounts_dir) if args.all else [
            resolve_policy_path(args.account, args.accounts_dir)
        ]
        if not policy_paths:
            raise ValueError(f"no account policies found in {args.accounts_dir}")

        failures = 0
        for index, policy_path in enumerate(policy_paths):
            try:
                if pipeline == "full":
                    result = FullPipelineOrchestrator(store).run(
                        topic=args.topic,
                        policy_path=policy_path,
                    )
                else:
                    result = Day1Orchestrator(store).run(
                        topic=args.topic,
                        policy_path=policy_path,
                    )
                if index:
                    print()
                _print_result(result, database=args.database, pipeline=pipeline)
            except (Day1RunError, FullPipelineError) as exc:
                failures += 1
                print(
                    f"Run {exc.run_id} failed at {exc.step.value} ({exc.code}): {exc}",
                    file=sys.stderr,
                )
                if not args.all:
                    return 3
        if failures:
            print(f"Batch completed with {failures} failed account(s).", file=sys.stderr)
            return 3
    except PolicyParseError as exc:
        print(f"Policy error: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"Input error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
