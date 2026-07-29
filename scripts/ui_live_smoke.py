"""Exercise Markdown upload -> review -> approve -> dry-run in the real Streamlit app."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from streamlit.testing.v1 import AppTest

from content_agent.platform import SQLiteRunStore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", default="responsible-ai-lab")
    parser.add_argument("--content-mode", choices=("generate", "publish"), default="generate")
    parser.add_argument(
        "--topic",
        default="Pre-publish checks for AI-assisted social content",
    )
    parser.add_argument(
        "--instructions",
        default=(
            "Write a practical three-step post about the topic and end "
            "with one question for small-team leaders."
        ),
    )
    parser.add_argument(
        "--source-content",
        default=(
            "Internal note: before publishing, verify factual claims, compare the "
            "draft with the account policy, and assign one human owner."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "artifacts" / "ui_live_smoke_report.json",
    )
    parser.add_argument("--timeout", type=float, default=180.0)
    return parser.parse_args()


def _element(elements, label: str):
    return next(element for element in elements if element.label == label)


def _errors(app: AppTest) -> list[str]:
    return [str(element.value) for element in app.error]


def main() -> int:
    args = parse_args()
    database = ROOT / "artifacts" / f"ui_live_smoke_{uuid4().hex}.sqlite3"
    database.parent.mkdir(parents=True, exist_ok=True)
    previous_database = os.environ.get("CONTENT_AGENT_DB")
    os.environ["CONTENT_AGENT_DB"] = str(database)
    report: dict = {
        "started_at": datetime.now(UTC).isoformat(),
        "account": args.account,
        "topic": args.topic,
        "content_mode": args.content_mode,
        "content_task": "create",
        "source_content_supplied": False,
        "database": str(database),
        "external_meta_called": False,
        "steps": [],
    }
    try:
        app = AppTest.from_file(
            str(ROOT / "streamlit_app.py"),
            default_timeout=args.timeout,
        ).run(timeout=args.timeout)
        if list(app.exception):
            raise RuntimeError(f"initial render failed: {list(app.exception)}")
        report["steps"].append("rendered")

        _element(app.selectbox, "Kênh & phong cách").set_value(args.account)
        if args.content_mode == "generate":
            markdown = f"""---
mode: generate
task: create
pipeline: full
---
# Topic
{args.topic}
# Instructions
{args.instructions}
"""
        else:
            markdown = f"""---
mode: publish
task: create
pipeline: full
---
# Topic
{args.topic}
# Content
{args.source_content}

#ResponsibleAI
"""
        _element(app.file_uploader, "Upload content Markdown *").upload(
            "ui-live-smoke.md",
            markdown.encode("utf-8"),
            "text/markdown",
        )
        app.run(timeout=args.timeout)
        _element(app.button, "Chạy content Markdown").click()
        app.run(timeout=args.timeout)
        if _errors(app):
            raise RuntimeError("generation UI error: " + " | ".join(_errors(app)))

        store = SQLiteRunStore(database)
        queue = store.list_review_queue()
        if len(queue) != 1:
            raise RuntimeError(f"expected one review item after generation, found {len(queue)}")
        run_id = queue[0]["run_id"]
        content_request = store.get_content_request(run_id)
        draft = store.get_current_draft(run_id)
        if args.content_mode == "generate":
            research = store.get_research(run_id)
            if research.request_id != content_request.request_id:
                raise RuntimeError("Research brief lost the content request lineage")
        if draft.request_id != content_request.request_id:
            raise RuntimeError("Draft post lost the content request lineage")
        report["run_id"] = run_id
        report["request_id"] = str(content_request.request_id)
        report["request_mode"] = content_request.mode.value
        report["source_type"] = content_request.source_type.value
        report["source_characters"] = len(content_request.source_content)
        report["research_request_match"] = args.content_mode == "generate"
        report["draft_request_match"] = True
        report["critic_score"] = queue[0]["score"]
        report["steps"].append("generated_to_human_review")

        _element(app.text_input, "Operator").set_value("ui-live-smoke")
        _element(app.text_area, "Approval note (required)").set_value(
            "Smoke reviewer checked the final content, policy constraints, score, and CTA."
        )
        _element(app.button, "Approve and move to Publish").click()
        try:
            app.run(timeout=args.timeout)
        except KeyError as exc:
            if "review_run" not in str(exc):
                raise
        if store.get_workflow(run_id)["state"] != "approved":
            raise RuntimeError("workflow did not enter approved state")
        report["steps"].append("approved")

        # Start a fresh browser-test session after the dynamic review widget is
        # removed from an empty queue. This mirrors a normal post-approval page
        # refresh and avoids retaining a stale AppTest widget handle.
        app = AppTest.from_file(
            str(ROOT / "streamlit_app.py"),
            default_timeout=args.timeout,
        ).run(timeout=args.timeout)
        if list(app.exception):
            raise RuntimeError(f"post-approval render failed: {list(app.exception)}")
        _element(app.button, "Run publishing dry-run").click()
        app.run(timeout=args.timeout)
        if _errors(app):
            raise RuntimeError("dry-run UI error: " + " | ".join(_errors(app)))
        workflow = store.get_workflow(run_id)
        attempts = store.get_publish_attempts(run_id)
        if workflow["state"] != "dry_run" or len(attempts) != 1:
            raise RuntimeError("publishing dry-run did not persist the expected receipt")
        report["steps"].append("publishing_dry_run")
        report["final_state"] = workflow["state"]
        report["review_actions"] = [action["action"] for action in store.get_review_actions(run_id)]
        report["publish_status"] = attempts[0]["status"]
        report["usage"] = store.usage_summary()["total"]
        report["completed_at"] = datetime.now(UTC).isoformat()
        report["status"] = "passed"
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"status=passed run_id={run_id} final_state={workflow['state']}")
        print(f"report={args.output}")
        return 0
    except Exception as exc:
        report["status"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["completed_at"] = datetime.now(UTC).isoformat()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(report["error"], file=sys.stderr)
        print(f"report={args.output}", file=sys.stderr)
        return 1
    finally:
        if previous_database is None:
            os.environ.pop("CONTENT_AGENT_DB", None)
        else:
            os.environ["CONTENT_AGENT_DB"] = previous_database


if __name__ == "__main__":
    raise SystemExit(main())
