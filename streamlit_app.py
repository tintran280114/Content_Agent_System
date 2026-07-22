"""Operations dashboard for the CLI-first Social Content Agent System."""

from __future__ import annotations

import os
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

load_dotenv(ROOT / ".env", override=False)

st.set_page_config(
    page_title="Social Content Ops",
    page_icon="🛡️",
    layout="wide",
)


def _load_cloud_secrets() -> None:
    try:
        secret_values = dict(st.secrets)
    except FileNotFoundError:
        return
    for key in (
        "GEMINI_API_KEY",
        "GEMINI_MODEL",
        "GROQ_API_KEY",
        "GROQ_MODEL",
        "GITHUB_MODELS_TOKEN",
        "GITHUB_MODELS_MODEL",
        "CONTENT_AGENT_DB",
    ):
        value = secret_values.get(key)
        if value and not os.environ.get(key):
            os.environ[key] = str(value)


def _valid_sqlite(data: bytes) -> bool:
    return data.startswith(b"SQLite format 3\x00") and len(data) <= 50 * 1024 * 1024


_load_cloud_secrets()
default_database = Path(os.environ.get("CONTENT_AGENT_DB", ROOT / "artifacts" / "day1.sqlite3"))
if not default_database.is_absolute():
    default_database = ROOT / default_database

if "database_path" not in st.session_state:
    st.session_state.database_path = str(default_database)

st.title("Social Content Operations")
st.caption("CLI-first batch pipeline · Hybrid Critic · Human review · Mock Publisher")

with st.sidebar:
    st.header("Database")
    database_input = st.text_input("SQLite path", value=st.session_state.database_path)
    if st.button("Open database", width="stretch"):
        selected = Path(database_input)
        if not selected.is_absolute():
            selected = ROOT / selected
        st.session_state.database_path = str(selected)
        st.rerun()

    uploaded = st.file_uploader("Upload an Actions SQLite snapshot", type=("sqlite3", "sqlite", "db"))
    if uploaded is not None and st.button("Use uploaded snapshot", width="stretch"):
        data = uploaded.getvalue()
        if not _valid_sqlite(data):
            st.error("Snapshot must be a valid SQLite file no larger than 50 MB.")
        else:
            target = ROOT / "artifacts" / "streamlit_uploaded.sqlite3"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            st.session_state.database_path = str(target)
            st.success("Snapshot loaded for this app instance.")
            st.rerun()

    st.info(
        "Community Cloud storage is runtime-local. Upload the latest GitHub Actions snapshot, "
        "then download the reviewed database before a reboot."
    )

database_path = Path(st.session_state.database_path)
try:
    store = SQLiteRunStore(database_path)
except Exception as exc:
    st.error(f"Could not open the SQLite database: {type(exc).__name__}")
    st.stop()

review_service = ReviewService(store)
runs = store.list_runs()
queue = store.list_review_queue()
usage = store.usage_summary()

metric_columns = st.columns(4)
metric_columns[0].metric("Runs", len(runs))
metric_columns[1].metric("Human queue", len(queue))
metric_columns[2].metric(
    "Published",
    sum(1 for run in runs if run.get("workflow_state") == "published"),
)
metric_columns[3].metric("Total tokens", f"{usage['total']['total_tokens']:,}")

overview_tab, review_tab, history_tab, usage_tab, deploy_tab = st.tabs(
    ["Overview", "Human review", "Run history", "Scores & usage", "Deploy"]
)

with overview_tab:
    st.subheader("Latest batch state")
    if not runs:
        st.info("No run data yet. Execute `python run.py --all --pipeline full` or upload a snapshot.")
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
                    "The latest AI Critic applies to an earlier revision. This human edit still requires "
                    "a manual approval note and must pass deterministic rules."
                )
            st.markdown("**Violations**")
            st.write(critic.violations or ["None"])
            st.markdown("**Suggestions**")
            st.write(critic.suggestions or ["None"])

        action_tabs = st.tabs(["Approve", "Reject", "Edit"])
        with action_tabs[0]:
            with st.form("approve_form"):
                actor = st.text_input("Operator", key="approve_actor")
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
                        st.success(receipt.reason)
                        st.rerun()
                    except (ValueError, KeyError, RuntimeError) as exc:
                        st.error(str(exc))

        with action_tabs[1]:
            with st.form("reject_form"):
                actor = st.text_input("Operator", key="reject_actor")
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
                        st.success("Draft rejected. Publisher guard remains closed.")
                        st.rerun()
                    except (ValueError, KeyError, RuntimeError) as exc:
                        st.error(str(exc))

        with action_tabs[2]:
            with st.form("edit_form"):
                actor = st.text_input("Operator", key="edit_actor")
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
                        st.success("Human edit saved as a new revision; explicit approval is still required.")
                        st.rerun()
                    except (ValueError, KeyError, RuntimeError) as exc:
                        st.error(str(exc))

        with st.expander("Audit trail"):
            st.dataframe(store.get_review_actions(selected_run), width="stretch", hide_index=True)
            st.dataframe(store.get_events(selected_run), width="stretch", hide_index=True)

with history_tab:
    st.subheader("Runs and terminal decisions")
    st.dataframe(runs, width="stretch", hide_index=True)

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

    st.subheader("Provider token and cost view")
    st.dataframe(usage["by_provider"], width="stretch", hide_index=True)
    if usage["total"]["estimated_cost_usd"] is None:
        st.caption("Estimated cost is unavailable for free-tier routes; token usage is still persisted.")

with deploy_tab:
    st.subheader("Snapshot handoff")
    if database_path.exists():
        st.download_button(
            "Download current SQLite snapshot",
            data=database_path.read_bytes(),
            file_name=database_path.name,
            mime="application/vnd.sqlite3",
            width="stretch",
        )
    st.code("streamlit run streamlit_app.py", language="bash")
    st.markdown(
        "For Community Cloud, deploy `streamlit_app.py` from the repository root, select Python 3.11, "
        "and keep provider credentials in Streamlit Secrets rather than the repository."
    )
