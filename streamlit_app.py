"""Review-only operations dashboard for the CLI-first content pipeline."""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from content_agent.platform import SQLiteRunStore
from content_agent.review import ReviewService
from content_agent.snapshot import install_sqlite_snapshot

st.set_page_config(
    page_title="Social Content Ops",
    page_icon="🛡️",
    layout="wide",
)


def _database_path() -> Path:
    configured = Path(
        os.environ.get("CONTENT_AGENT_DB", ROOT / "artifacts" / "content_agent.sqlite3")
    )
    return configured if configured.is_absolute() else ROOT / configured


def _set_notice(level: str, message: str) -> None:
    st.session_state["notice"] = {"level": level, "message": message}


def _show_notice() -> None:
    notice = st.session_state.pop("notice", None)
    if not notice:
        return
    renderer = {
        "success": st.success,
        "warning": st.warning,
        "error": st.error,
        "info": st.info,
    }.get(notice["level"], st.info)
    renderer(notice["message"])


load_dotenv(ROOT / ".env", override=False)
database_path = _database_path()

with st.sidebar:
    st.header("Content Agent Ops")
    st.caption("The CLI and scheduled workflow own content generation.")
    operator_identity = st.text_input(
        "Operator name or email",
        value=st.session_state.get("operator_identity", ""),
        key="operator_identity",
        help="Stored in approve, reject, and edit audit events.",
    )
    with st.expander("Cloud snapshot handoff"):
        st.caption(
            "For Streamlit Cloud only: load the SQLite artifact produced by the CLI or Actions."
        )
        uploaded = st.file_uploader(
            "SQLite snapshot",
            type=("sqlite3", "sqlite", "db"),
            label_visibility="collapsed",
        )
        if st.button("Load snapshot", disabled=uploaded is None, width="stretch"):
            try:
                install_sqlite_snapshot(uploaded.getvalue(), database_path)
                _set_notice("success", "SQLite snapshot loaded. Dashboard state is refreshed.")
                st.rerun()
            except (ValueError, OSError, sqlite3.DatabaseError) as exc:
                st.error(str(exc))

try:
    store = SQLiteRunStore(database_path)
except Exception as exc:
    st.error(f"The SQLite operations store could not start ({type(exc).__name__}).")
    st.stop()

review_service = ReviewService(store)
runs = store.list_runs()
queue = store.list_review_queue()
usage = store.usage_summary()

with st.sidebar:
    st.success("SQLite operations store ready")
    st.download_button(
        "Download SQLite evidence",
        data=store.backup_bytes(),
        file_name="content_agent.sqlite3",
        mime="application/vnd.sqlite3",
        width="stretch",
    )
    st.caption("Mock Publisher · no external database · no generation in this UI")

st.title("Social Content Operations")
st.caption("Queue · Human review · Score history · Token and cost audit")
_show_notice()

metric_columns = st.columns(4)
metric_columns[0].metric("Runs", len(runs))
metric_columns[1].metric("Human queue", len(queue))
metric_columns[2].metric(
    "Published",
    sum(1 for run in runs if run.get("workflow_state") == "published"),
)
metric_columns[3].metric("Total tokens", f"{usage['total']['total_tokens']:,}")

overview_tab, review_tab, history_tab, usage_tab = st.tabs(
    ["Overview", "Human review", "Run history", "Scores & usage"]
)

with overview_tab:
    st.subheader("Latest scheduled batch state")
    if not runs:
        st.info(
            "No run data yet. Run `python run.py --account <slug>` or `python run.py --all`, "
            "then refresh this dashboard."
        )
    else:
        overview_fields = [
            "run_id",
            "account_id",
            "topic",
            "state",
            "workflow_state",
            "rewrite_count",
            "score",
            "created_at",
        ]
        st.dataframe(
            [{field: row.get(field) for field in overview_fields} for row in runs],
            width="stretch",
            hide_index=True,
        )

with review_tab:
    st.subheader("Human review queue")
    if not queue:
        st.success("Queue is empty.")
    else:
        labels = {
            row["run_id"]: f"{row['account_id']} · score {row.get('score', 'n/a')} · {row['run_id'][:8]}"
            for row in queue
        }
        selected_run = st.selectbox(
            "Review item",
            options=list(labels),
            format_func=lambda run_id: labels[run_id],
            key="review_run",
        )
        item = next(row for row in queue if row["run_id"] == selected_run)
        draft = store.get_current_draft(selected_run)
        policy = store.get_policy(selected_run)
        critic = store.get_latest_critic(selected_run)

        left, right = st.columns([2, 1])
        with left:
            st.markdown(f"**Account:** `{policy.account_id}` · **Platform:** {policy.platform}")
            st.text_area("Current content", value=draft.content, height=180, disabled=True)
            st.write("Hashtags:", " ".join(draft.hashtags) or "—")
            st.write("Call to action:", draft.call_to_action or "—")
        with right:
            st.metric("Critic score", critic.score if critic else "Unavailable")
            st.metric("AI rewrites", item["rewrite_count"])
            st.write("Threshold:", policy.threshold)
            if item.get("last_error_code"):
                st.warning(f"{item['last_error_code']}: {item['last_error_message']}")

        if critic:
            if str(critic.draft_id) != str(draft.draft_id):
                st.info(
                    "The latest AI Critic applies to an earlier revision. This human edit still "
                    "requires a note and must pass deterministic rules before approval."
                )
            st.markdown("**Violations**")
            st.write(critic.violations or ["None"])
            st.markdown("**Suggestions**")
            st.write(critic.suggestions or ["None"])

        action_tabs = st.tabs(["Approve", "Reject", "Edit"])
        with action_tabs[0]:
            with st.form("approve_form"):
                actor = st.text_input("Operator", value=operator_identity, key="approve_actor")
                note = st.text_area("Approval note (required)", key="approve_note")
                submitted = st.form_submit_button("Approve and mock-publish")
                if submitted:
                    try:
                        receipt = review_service.approve(
                            selected_run,
                            actor=actor,
                            note=note,
                            expected_version=int(item["version"]),
                        )
                        _set_notice("success", receipt.reason)
                        st.rerun()
                    except (ValueError, KeyError, RuntimeError) as exc:
                        st.error(str(exc))

        with action_tabs[1]:
            with st.form("reject_form"):
                actor = st.text_input("Operator", value=operator_identity, key="reject_actor")
                note = st.text_area("Rejection note", key="reject_note")
                submitted = st.form_submit_button("Reject permanently")
                if submitted:
                    try:
                        review_service.reject(
                            selected_run,
                            actor=actor,
                            note=note,
                            expected_version=int(item["version"]),
                        )
                        _set_notice("success", "Draft rejected. Publisher guard remains closed.")
                        st.rerun()
                    except (ValueError, KeyError, RuntimeError) as exc:
                        st.error(str(exc))

        with action_tabs[2]:
            with st.form("edit_form"):
                actor = st.text_input("Operator", value=operator_identity, key="edit_actor")
                edited_content = st.text_area("Edited content", value=draft.content, height=180)
                note = st.text_area("Edit note", key="edit_note")
                submitted = st.form_submit_button("Save human edit")
                if submitted:
                    try:
                        review_service.edit(
                            selected_run,
                            actor=actor,
                            content=edited_content,
                            note=note,
                            expected_version=int(item["version"]),
                        )
                        _set_notice(
                            "success",
                            "Human edit saved as a new revision; explicit approval is still required.",
                        )
                        st.rerun()
                    except (ValueError, KeyError, RuntimeError) as exc:
                        st.error(str(exc))

        with st.expander("Audit and revision trail"):
            st.dataframe(store.get_review_actions(selected_run), width="stretch", hide_index=True)
            st.dataframe(store.get_events(selected_run), width="stretch", hide_index=True)
            st.json(store.get_draft_revisions(selected_run))
            st.json(store.get_critic_results(selected_run))

with history_tab:
    st.subheader("Runs, content, and terminal decisions")
    if not runs:
        st.info("No run history has been recorded.")
    else:
        st.dataframe(runs, width="stretch", hide_index=True)
        history_run = st.selectbox(
            "Inspect run",
            options=[run["run_id"] for run in runs],
            format_func=lambda run_id: next(
                f"{run['account_id']} · {run_id[:8]} · {run.get('workflow_state') or run['state']}"
                for run in runs
                if run["run_id"] == run_id
            ),
            key="history_run",
        )
        selected = next(run for run in runs if run["run_id"] == history_run)
        artifacts = store.get_artifacts(history_run)
        content = artifacts.get("draft_post", {}).get("payload", {})
        if selected.get("workflow_state"):
            content = store.get_current_draft(history_run).model_dump(mode="json")
        st.text_area(
            "Persisted content",
            value=str(content.get("content", "No draft was produced.")),
            height=160,
            disabled=True,
        )
        detail_tabs = st.tabs(
            ["Events", "Revisions", "Critics", "Review actions", "Publish attempts", "Artifacts"]
        )
        detail_tabs[0].dataframe(store.get_events(history_run), width="stretch", hide_index=True)
        detail_tabs[1].json(store.get_draft_revisions(history_run))
        detail_tabs[2].json(store.get_critic_results(history_run))
        detail_tabs[3].dataframe(
            store.get_review_actions(history_run), width="stretch", hide_index=True
        )
        detail_tabs[4].dataframe(
            store.get_publish_attempts(history_run), width="stretch", hide_index=True
        )
        detail_tabs[5].json(artifacts)

with usage_tab:
    score_rows = store.score_history()
    st.subheader("Critic score history")
    if score_rows:
        score_frame = pd.DataFrame(score_rows)
        score_frame["created_at"] = pd.to_datetime(score_frame["created_at"])
        st.line_chart(score_frame, x="created_at", y="score", color="account_id")
        st.dataframe(score_frame, width="stretch", hide_index=True)
    else:
        st.info("No Critic scores have been recorded.")

    st.subheader("Token, cost, and retry per post/account")
    if usage["by_run"]:
        st.dataframe(usage["by_run"], width="stretch", hide_index=True)
    else:
        st.info("No provider usage has been recorded.")

    st.subheader("Provider/model quota audit")
    if usage["by_provider"]:
        st.dataframe(usage["by_provider"], width="stretch", hide_index=True)
    else:
        st.info("No provider usage has been recorded.")
    if usage["total"]["estimated_cost_usd"] is None:
        st.caption("Free-tier routes may report no dollar estimate; token/request usage is persisted.")
