"""Run the CLI-first social-content batch pipeline."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from dotenv import load_dotenv

from content_agent.ai.models import ContentTask
from content_agent.orchestrator import PipelineMode, PipelineOrchestrator, PipelineRunError
from content_agent.platform import SQLiteRunStore
from content_agent.policy import PolicyParseError, load_policies, load_policy
from content_agent.publisher import PolicyPublisherRouter, PublishError

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
    action.add_argument(
        "--publish-approved",
        metavar="RUN_ID",
        help="Publish one already-approved run without calling an LLM provider.",
    )
    parser.add_argument("--topic", default=DEFAULT_TOPIC, help="Topic supplied to the Research Agent.")
    parser.add_argument(
        "--instructions",
        default="",
        help="Operator brief: angle, audience need, CTA, or other trusted writing directions.",
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--content",
        default="",
        help="Source content to transform. Prefer --content-file for long Markdown or text.",
    )
    source.add_argument(
        "--content-file",
        type=Path,
        help="UTF-8 .md or .txt source material; kept separate from the account policy.",
    )
    parser.add_argument(
        "--content-task",
        choices=tuple(task.value for task in ContentTask),
        default=ContentTask.CREATE.value,
        help="How to use source content: create, repurpose, rewrite, or summarize.",
    )
    parser.add_argument(
        "--pipeline",
        choices=("draft", "full"),
        help=(
            "draft preserves the Day 1 slice; full adds Critic, rewrites, review, and guarded "
            "policy-selected publishing. Default: full."
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
        default=ROOT / "artifacts" / "content_agent.sqlite3",
        help="SQLite database path (default: artifacts/content_agent.sqlite3).",
    )
    parser.add_argument(
        "--publish-mode",
        choices=("dry-run", "live"),
        default="dry-run",
        help="External publisher gate. Default: dry-run; live can call Meta APIs.",
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
    print("state=completed")
    print(f"account={result.policy.account_id}")
    print(f"content_task={result.request.task.value if result.request else 'create'}")
    print(f"source_content={result.request.source_type.value if result.request else 'none'}")
    print(f"research_brief_id={result.research.brief_id}")
    print(f"draft_post_id={result.draft.draft_id}")
    if pipeline == "full":
        print(f"workflow_state={result.workflow_state.value}")
        print(f"rewrite_count={result.rewrite_count}")
        print(f"critic_score={result.critic.score if result.critic else 'unavailable'}")
        if result.terminal_error_code:
            print(f"terminal_error_code={result.terminal_error_code}")
    print(f"database={database}")


def _print_publish_receipt(receipt, *, database: Path) -> None:
    print(f"publish_id={receipt.publish_id}")
    print(f"publish_status={receipt.status.value}")
    print(f"destination={receipt.destination}")
    print(f"remote_post_id={receipt.remote_post_id or 'none'}")
    print(f"topic_tag={receipt.topic_tag or 'none'}")
    print(f"reason={receipt.reason}")
    print(f"database={database}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_dotenv(ROOT / ".env", override=False)
    pipeline = args.pipeline or "full"

    try:
        if args.list_accounts:
            paths = _policy_files(args.accounts_dir)
            policies = load_policies(paths)
            for policy in policies:
                credential_ref = policy.publishing.credential_ref
                credential_present = (
                    str(bool(os.environ.get(credential_ref, "").strip())).lower() if credential_ref else "n/a"
                )
                topic_tag_mode = (
                    "trend"
                    if policy.publishing.trend_search
                    else ("fixed" if policy.publishing.topic_tag else "none")
                )
                print(
                    f"{policy.account_id}\t{policy.platform}\tactive={str(policy.active).lower()}"
                    f"\tpublisher={policy.publishing.adapter}\tmax_length={policy.max_length}"
                    f"\tcredential_ref={credential_ref or 'none'}"
                    f"\tcredential_present={credential_present}"
                    f"\ttopic_tag_mode={topic_tag_mode}"
                )
            return 0

        store = SQLiteRunStore(args.database)
        publisher = PolicyPublisherRouter(store, mode=args.publish_mode)
        if args.publish_approved:
            receipt = publisher.publish(args.publish_approved)
            _print_publish_receipt(receipt, database=args.database)
            return 0

        if args.all:
            discovered_paths = _policy_files(args.accounts_dir)
            policies = load_policies(discovered_paths)
            policy_paths = [path for path, policy in zip(discovered_paths, policies) if policy.active]
        else:
            policy_path = resolve_policy_path(args.account, args.accounts_dir)
            policy = load_policy(policy_path)
            if not policy.active:
                raise ValueError(f"account '{policy.account_id}' is inactive; set active: true to run it")
            policy_paths = [policy_path]
        if not policy_paths:
            raise ValueError(f"no active account policies found in {args.accounts_dir}")

        source_content = args.content
        source_name = None
        if args.content_file:
            if args.content_file.suffix.casefold() not in {".md", ".txt"}:
                raise ValueError("--content-file must be a UTF-8 .md or .txt file")
            try:
                source_content = args.content_file.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeError) as exc:
                raise ValueError(f"cannot read source content file: {args.content_file}") from exc
            source_name = args.content_file.name

        failures = 0
        for index, policy_path in enumerate(policy_paths):
            try:
                result = PipelineOrchestrator(store, publisher=publisher).run(
                    topic=args.topic,
                    instructions=args.instructions,
                    source_content=source_content,
                    source_name=source_name,
                    task=args.content_task,
                    policy_path=policy_path,
                    mode=PipelineMode(pipeline),
                )
                if index:
                    print()
                _print_result(result, database=args.database, pipeline=pipeline)
                if result.terminal_error_code == "quota_exhausted":
                    print(
                        "Batch stopped because a provider/application daily quota was exhausted.",
                        file=sys.stderr,
                    )
                    return 4
            except PipelineRunError as exc:
                failures += 1
                print(
                    f"Run {exc.run_id} failed at {exc.step.value} ({exc.code}): {exc}",
                    file=sys.stderr,
                )
                if exc.code == "quota_exhausted":
                    print("Batch stopped before the next account to protect quota.", file=sys.stderr)
                    return 4
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
    except KeyError as exc:
        print(f"Input error: {exc}", file=sys.stderr)
        return 2
    except PublishError as exc:
        print(f"Publish error ({exc.code}): {exc}", file=sys.stderr)
        return 5
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
