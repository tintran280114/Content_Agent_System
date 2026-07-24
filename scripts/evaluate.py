"""Run or resume the fixed Wednesday 10-topic x three-policy evaluation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from dotenv import load_dotenv

from content_agent.evaluation import EvaluationRunner, write_report
from content_agent.platform import SQLiteRunStore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation-id", default="wednesday-v1")
    parser.add_argument("--topics", type=Path, default=ROOT / "evaluation" / "topics.json")
    parser.add_argument("--accounts-dir", type=Path, default=ROOT / "accounts")
    parser.add_argument("--database", type=Path, default=ROOT / "artifacts" / "evaluation.sqlite3")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts" / "evaluation_report.json")
    parser.add_argument("--limit", type=int, help="Run only the first N cases for a smoke check.")
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Rerun cases instead of skipping completed ones.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_dotenv(ROOT / ".env", override=False)
    topics = json.loads(args.topics.read_text(encoding="utf-8"))
    if (
        not isinstance(topics, list)
        or len(topics) != 10
        or not all(isinstance(item, str) and item.strip() for item in topics)
    ):
        print("Evaluation topics file must contain exactly 10 strings.", file=sys.stderr)
        return 2
    policies = sorted(path for path in args.accounts_dir.glob("*.md") if path.name != "template.md")
    if len(policies) != 3:
        print("Evaluation requires exactly three account policies.", file=sys.stderr)
        return 2

    runner = EvaluationRunner(SQLiteRunStore(args.database))

    def save_progress(report: dict) -> None:
        write_report(args.output, report)
        print(
            f"progress={report['completed'] + report['failed']}/{report['total_cases']} "
            f"completed={report['completed']} failed={report['failed']}"
        )

    report = runner.run(
        evaluation_id=args.evaluation_id,
        topics=topics,
        policy_paths=policies,
        resume=not args.no_resume,
        limit=args.limit,
        progress=save_progress,
    )
    write_report(args.output, report)
    print(f"report={args.output}")
    return 0 if report["failed"] == 0 else 3


if __name__ == "__main__":
    raise SystemExit(main())
