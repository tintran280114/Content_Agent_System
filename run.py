"""Run the Day 1 policy-to-draft vertical slice."""

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
        "--list-accounts",
        action="store_true",
        help="Validate and list available account policies without calling a provider.",
    )
    parser.add_argument("--topic", default=DEFAULT_TOPIC, help="Topic supplied to the Research Agent.")
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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_dotenv(ROOT / ".env", override=False)

    try:
        if args.list_accounts:
            policies = load_policies(_policy_files(args.accounts_dir))
            for policy in policies:
                print(f"{policy.account_id}\t{policy.platform}\tmax_length={policy.max_length}")
            return 0

        policy_path = resolve_policy_path(args.account, args.accounts_dir)
        store = SQLiteRunStore(args.database)
        result = Day1Orchestrator(store).run(topic=args.topic, policy_path=policy_path)
    except PolicyParseError as exc:
        print(f"Policy error: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"Input error: {exc}", file=sys.stderr)
        return 2
    except Day1RunError as exc:
        print(
            f"Run {exc.run_id} failed at {exc.step.value} ({exc.code}): {exc}",
            file=sys.stderr,
        )
        return 3

    print(f"run_id={result.run_id}")
    print(f"state=completed")
    print(f"account={result.policy.account_id}")
    print(f"research_brief_id={result.research.brief_id}")
    print(f"draft_post_id={result.draft.draft_id}")
    print(f"database={args.database}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
