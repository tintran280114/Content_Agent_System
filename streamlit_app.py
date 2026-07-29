"""Guided end-to-end social content studio and operations dashboard."""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path
from secrets import token_urlsafe

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from content_agent.ai.config import DEFAULT_ROUTES, Role
from content_agent.ai.connectivity import probe_all_connections
from content_agent.ai.models import ContentMode
from content_agent.ai.registry import create_role_provider
from content_agent.content_markdown import (
    GENERATE_TEMPLATE,
    PUBLISH_TEMPLATE,
    ContentMarkdownError,
    import_publish_document,
    metadata_summary,
    parse_content_markdown,
)
from content_agent.critics import render_post
from content_agent.meta_auth import (
    EncryptedTokenStore,
    MetaAuthError,
    ThreadsOAuthClient,
    ThreadsTokenManager,
    build_threads_authorization_url,
)
from content_agent.orchestrator import PipelineMode, PipelineOrchestrator, PipelineRunError
from content_agent.platform import SQLiteRunStore
from content_agent.policy import PolicyParseError, load_policy, parse_policy_text
from content_agent.policy_builder import (
    PolicyBuilderInput,
    render_policy_markdown,
    save_policy_markdown,
    split_lines,
)
from content_agent.publisher import (
    EnvironmentCredentialResolver,
    PolicyPublisherRouter,
    PublishError,
)
from content_agent.review import ReviewService
from content_agent.snapshot import install_sqlite_snapshot, save_rotating_snapshot

st.set_page_config(
    page_title="Social Content Studio",
    page_icon="✨",
    layout="wide",
    initial_sidebar_state="expanded",
)

PROVIDER_CREDENTIALS = {
    "GEMINI_API_KEY": "Gemini · Research",
    "GROQ_API_KEY": "Groq · Copywriter",
    "GITHUB_MODELS_TOKEN": "GitHub Models · Critic",
}

META_CONFIGURATION = (
    "CONTENT_AGENT_TOKEN_ENCRYPTION_KEY",
    "CONTENT_AGENT_TOKEN_STORE",
    "META_REQUEST_TIMEOUT_SECONDS",
    "THREADS_APP_ID",
    "THREADS_APP_SECRET",
    "THREADS_REDIRECT_URI",
    "THREADS_TOKEN_REFRESH_DAYS",
)


def _inject_styles() -> None:
    st.markdown(
        """
        <style>
        :root {
          --ink: #111827;
          --muted: #64748b;
          --brand: #6d5dfc;
          --brand-2: #14b8a6;
          --panel: rgba(255,255,255,.88);
        }
        .stApp {
          background:
            radial-gradient(circle at 88% 2%, rgba(109,93,252,.12), transparent 25rem),
            radial-gradient(circle at 12% 22%, rgba(20,184,166,.08), transparent 22rem),
            #f7f8fc;
        }
        [data-testid="stSidebar"] {
          background:
            radial-gradient(circle at 0% 0%, rgba(124,58,237,.22), transparent 18rem),
            linear-gradient(180deg, #0b1220 0%, #111c36 100%);
          border-right: 1px solid rgba(148,163,184,.18);
        }
        [data-testid="stSidebar"] h1,
        [data-testid="stSidebar"] h2,
        [data-testid="stSidebar"] h3,
        [data-testid="stSidebar"] label,
        [data-testid="stSidebar"] p {
          color: #eef2ff;
        }
        [data-testid="stSidebar"] [data-testid="stCaptionContainer"] p {
          color: #b8c3d9;
        }
        [data-testid="stSidebar"] input {
          color: #111827 !important;
          background: #ffffff !important;
          border-radius: 12px;
        }
        [data-testid="stSidebar"] button {
          color: #172033 !important;
          background: #f8fafc;
          border: 1px solid rgba(148,163,184,.42);
          border-radius: 12px;
          font-weight: 700;
        }
        [data-testid="stSidebar"] button p {
          color: inherit !important;
        }
        [data-testid="stSidebar"] button[kind="primary"] {
          color: #ffffff !important;
          background: linear-gradient(110deg, #6d5dfc, #4f46e5);
          border: 0;
        }
        [data-testid="stSidebar"] details {
          background: rgba(255,255,255,.055);
          border: 1px solid rgba(148,163,184,.16);
          border-radius: 16px;
          padding: .15rem .35rem;
        }
        [data-testid="stSidebar"] code {
          color: #dbeafe;
          background: rgba(99,102,241,.24);
          border-radius: 6px;
          padding: .1rem .35rem;
        }
        [data-testid="stSidebar"] [data-testid="stAlert"] * { color: inherit; }
        .hero {
          border-radius: 24px;
          padding: 2rem 2.2rem;
          color: white;
          background: linear-gradient(120deg, #4f46e5 0%, #7c3aed 52%, #0f766e 100%);
          box-shadow: 0 18px 48px rgba(79,70,229,.22);
          margin-bottom: 1rem;
        }
        .hero h1 { margin: 0 0 .45rem; font-size: 2.35rem; letter-spacing: -.04em; }
        .hero p { margin: 0; opacity: .9; font-size: 1.04rem; }
        .flow {
          display: grid;
          grid-template-columns: repeat(6, minmax(105px, 1fr));
          gap: .55rem;
          margin: .8rem 0 1.3rem;
        }
        .flow-step {
          background: var(--panel);
          border: 1px solid rgba(148,163,184,.25);
          border-radius: 14px;
          padding: .72rem .8rem;
          box-shadow: 0 5px 18px rgba(15,23,42,.05);
          font-size: .82rem;
          color: var(--ink);
        }
        .flow-step b {
          display: block;
          color: var(--brand);
          font-size: .72rem;
          text-transform: uppercase;
          letter-spacing: .06em;
          margin-bottom: .18rem;
        }
        [data-testid="stMetric"] {
          background: var(--panel);
          border: 1px solid rgba(148,163,184,.22);
          border-radius: 16px;
          padding: .8rem 1rem;
          box-shadow: 0 5px 20px rgba(15,23,42,.05);
        }
        [data-testid="stTabs"] button { font-weight: 700; }
        div[data-testid="stForm"] {
          background: rgba(255,255,255,.72);
          border: 1px solid rgba(148,163,184,.25);
          border-radius: 22px;
          padding: 1.15rem;
          box-shadow: 0 12px 34px rgba(15,23,42,.06);
        }
        .hint-card {
          border-left: 4px solid var(--brand);
          background: rgba(255,255,255,.82);
          border-radius: 12px;
          padding: .9rem 1rem;
          margin: .5rem 0;
        }
        .composer-intro {
          border: 1px solid rgba(109,93,252,.2);
          background: linear-gradient(120deg, rgba(109,93,252,.1), rgba(20,184,166,.08));
          border-radius: 18px;
          padding: 1rem 1.15rem;
          margin: .4rem 0 1rem;
        }
        .composer-intro strong {
          display: block;
          color: #4338ca;
          font-size: 1.03rem;
          margin-bottom: .25rem;
        }
        .status-chip {
          display: inline-block;
          border-radius: 999px;
          padding: .2rem .55rem;
          margin: .08rem 0 .45rem;
          color: #d1fae5;
          background: rgba(16,185,129,.16);
          border: 1px solid rgba(52,211,153,.28);
          font-size: .78rem;
          font-weight: 700;
        }
        @media (max-width: 900px) {
          .flow { grid-template-columns: repeat(2, 1fr); }
          .hero h1 { font-size: 1.8rem; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _database_path() -> Path:
    configured = Path(os.environ.get("CONTENT_AGENT_DB", ROOT / "artifacts" / "content_agent.sqlite3"))
    return configured if configured.is_absolute() else ROOT / configured


def _policy_paths() -> list[Path]:
    return sorted(path for path in (ROOT / "accounts").glob("*.md") if path.name != "template.md")


def _policy_catalog() -> tuple[dict[str, tuple[Path, object]], list[str]]:
    catalog: dict[str, tuple[Path, object]] = {}
    errors: list[str] = []
    for path in _policy_paths():
        try:
            policy = load_policy(path)
            catalog[policy.account_id] = (path, policy)
        except (PolicyParseError, ValueError) as exc:
            errors.append(str(exc))
    return catalog, errors


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


def _configured_secret(key: str) -> str:
    environment_value = os.environ.get(key, "").strip()
    if environment_value:
        return environment_value
    try:
        deployed_value = str(st.secrets.get(key, "")).strip()
    except Exception:
        deployed_value = ""
    return deployed_value


def _credential_source(key: str) -> str:
    manual = str(st.session_state.get(f"runtime_secret_{key}", "") or "").strip()
    if manual:
        return "manual"
    if _configured_secret(key):
        return "system"
    return "missing"


def _runtime_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    runtime = dict(os.environ)
    for credential in (*PROVIDER_CREDENTIALS, *META_CONFIGURATION):
        override = st.session_state.get(f"runtime_secret_{credential}", "").strip()
        value = override or _configured_secret(credential)
        if value:
            runtime[credential] = value
    for key, raw_value in st.session_state.items():
        if key.startswith("runtime_secret_") and str(raw_value or "").strip():
            runtime[key.removeprefix("runtime_secret_")] = str(raw_value).strip()
        if key.startswith("runtime_expiry_") and str(raw_value or "").strip():
            credential_ref = key.removeprefix("runtime_expiry_")
            runtime[f"{credential_ref}_EXPIRES_AT"] = str(raw_value).strip()
    if extra:
        runtime.update({key: value for key, value in extra.items() if value.strip()})
    return runtime


def _missing_provider_credentials() -> list[str]:
    runtime = _runtime_env()
    return [key for key in PROVIDER_CREDENTIALS if not runtime.get(key, "").strip()]


def _clear_manual_credentials() -> None:
    for credential in PROVIDER_CREDENTIALS:
        st.session_state.pop(f"runtime_secret_{credential}", None)
    st.session_state.pop("connection_probe_results", None)
    st.session_state["notice"] = {
        "level": "info",
        "message": "Đã xóa key nhập tay; app đang dùng key mặc định của hệ thống.",
    }


def _render_social_connections(catalog: dict[str, tuple[Path, object]]) -> None:
    """Render platform credentials without exposing their values."""

    facebook = [
        (account_id, policy)
        for account_id, (_, policy) in catalog.items()
        if policy.publishing.adapter == "facebook_page"
    ]
    threads = [
        (account_id, policy)
        for account_id, (_, policy) in catalog.items()
        if policy.publishing.adapter == "threads"
    ]
    st.caption(
        "Token nhập tay chỉ ở trong browser session. Token lưu lâu dài được mã hóa "
        "và không nằm trong Markdown hoặc SQLite."
    )
    st.markdown("**Facebook Pages**")
    if not facebook:
        st.caption("Chưa có Facebook Page policy.")
    for account_id, policy in facebook:
        credential_ref = policy.publishing.credential_ref
        configured = bool(credential_ref and _runtime_env().get(credential_ref, "").strip())
        icon = "✅" if configured else "⚠️"
        st.caption(
            f"{icon} `{account_id}` · Page `{policy.publishing.target_id}` · "
            f"`{credential_ref or 'no credential_ref'}`"
        )

    st.markdown("**Threads**")
    if not threads:
        st.caption("Chưa có Threads policy. Tạo một policy ở tab Accounts trước.")
        return
    selected_account = st.selectbox(
        "Threads account",
        options=[account_id for account_id, _ in threads],
        key="threads_connection_account",
    )
    policy = next(policy for account_id, policy in threads if account_id == selected_account)
    credential_ref = str(policy.publishing.credential_ref)
    runtime = _runtime_env(
        {
            str(item_policy.publishing.credential_ref): _configured_secret(
                str(item_policy.publishing.credential_ref)
            )
            for _, item_policy in threads
            if item_policy.publishing.credential_ref
        }
    )
    status = None
    try:
        token_store = EncryptedTokenStore.from_env(runtime, base_dir=ROOT)
        manager = ThreadsTokenManager(env=runtime, store=token_store)
        status = manager.status(credential_ref)
        if status.configured:
            st.success(
                f"Threads token configured from `{status.source}`"
                + (
                    f" · expires `{status.expires_at:%Y-%m-%d}`"
                    if status.expires_at
                    else " · expiry unknown"
                )
            )
        else:
            st.warning("Threads chưa kết nối.")
        if not status.persistent_rotation:
            st.caption(
                "Auto-refresh qua network đã sẵn sàng, nhưng muốn lưu token mới qua restart "
                "hãy cấu hình `CONTENT_AGENT_TOKEN_ENCRYPTION_KEY`."
            )
    except MetaAuthError as exc:
        token_store = None
        manager = None
        st.error(f"Threads token store: {exc}")

    manual_token = st.text_input(
        f"{credential_ref} (session only)",
        type="password",
        key=f"runtime_secret_{credential_ref}",
        placeholder=(
            "Không bắt buộc · đang dùng token hệ thống"
            if _configured_secret(credential_ref)
            else "Dán Threads long-lived token"
        ),
    )
    token_days = st.number_input(
        "Token còn hiệu lực khoảng bao nhiêu ngày?",
        min_value=1,
        max_value=60,
        value=60,
        key=f"threads_token_days_{credential_ref}",
        help="Dùng expires_in Meta trả về nếu bạn biết giá trị chính xác.",
    )
    if st.button(
        "Lưu/kích hoạt Threads token",
        width="stretch",
        disabled=not bool(manual_token.strip()),
        key=f"save_threads_token_{credential_ref}",
    ):
        try:
            refreshed_runtime = _runtime_env()
            active_store = EncryptedTokenStore.from_env(refreshed_runtime, base_dir=ROOT)
            active_manager = ThreadsTokenManager(env=refreshed_runtime, store=active_store)
            record = active_manager.save_long_lived_token(
                credential_ref,
                access_token=manual_token,
                expires_in=int(token_days) * 24 * 60 * 60,
                user_id=str(policy.publishing.target_id),
            )
            st.session_state[f"runtime_secret_{credential_ref}"] = record.access_token
            st.session_state[f"runtime_expiry_{credential_ref}"] = record.expires_at.isoformat()
            _set_notice(
                "success",
                (
                    "Threads token đã được mã hóa và lưu lâu dài."
                    if active_store
                    else "Threads token đang hoạt động trong browser session này."
                ),
            )
            st.rerun()
        except MetaAuthError as exc:
            st.error(str(exc))

    if manager and status and status.configured and status.expires_at:
        if st.button(
            "Refresh Threads token ngay",
            width="stretch",
            key=f"refresh_threads_token_{credential_ref}",
        ):
            try:
                record = manager.refresh(credential_ref)
                st.session_state[f"runtime_secret_{credential_ref}"] = record.access_token
                st.session_state[f"runtime_expiry_{credential_ref}"] = record.expires_at.isoformat()
                _set_notice(
                    "success",
                    f"Threads token refreshed; hạn mới `{record.expires_at:%Y-%m-%d}`.",
                )
                st.rerun()
            except MetaAuthError as exc:
                st.error(str(exc))

    with st.expander(
        "OAuth setup · lấy Threads token",
        expanded=not bool(status and status.configured),
    ):
        st.caption(
            "Tạo Meta App có Threads use case, cấu hình redirect URI, rồi dùng nút đăng nhập. "
            "App Secret chỉ dùng phía server trong phiên này hoặc từ system secrets."
        )
        app_id = st.text_input(
            "Threads App ID",
            value=_configured_secret("THREADS_APP_ID"),
            key="threads_oauth_app_id",
        )
        app_secret_override = st.text_input(
            "Threads App Secret",
            type="password",
            key="runtime_secret_THREADS_APP_SECRET",
            placeholder=(
                "Đang dùng system secret"
                if _configured_secret("THREADS_APP_SECRET")
                else "Dán App Secret"
            ),
        )
        redirect_uri = st.text_input(
            "OAuth Redirect URI",
            value=_configured_secret("THREADS_REDIRECT_URI") or "http://localhost:8501",
            key="threads_oauth_redirect_uri",
        )
        state_key = f"threads_oauth_state_{credential_ref}"
        if state_key not in st.session_state:
            st.session_state[state_key] = token_urlsafe(24)
        try:
            authorization_url = build_threads_authorization_url(
                app_id=app_id,
                redirect_uri=redirect_uri,
                state=st.session_state[state_key],
                include_keyword_search=bool(policy.publishing.trend_search),
            )
        except MetaAuthError:
            authorization_url = "https://developers.facebook.com/apps/"
        st.link_button(
            "1 · Đăng nhập và cấp quyền Threads",
            authorization_url,
            width="stretch",
            disabled=not bool(app_id.strip() and redirect_uri.strip()),
        )
        callback_code = str(st.query_params.get("code", "") or "")
        callback_state = str(st.query_params.get("state", "") or "")
        authorization_code = st.text_input(
            "2 · Authorization code",
            value=callback_code,
            key="threads_oauth_code",
            help="App tự đọc query `code` sau redirect; bạn cũng có thể paste code thủ công.",
        )
        if st.button(
            "3 · Exchange code và kết nối",
            type="primary",
            width="stretch",
            disabled=not bool(authorization_code.strip()),
            key=f"exchange_threads_code_{credential_ref}",
        ):
            try:
                if callback_state and callback_state != st.session_state[state_key]:
                    raise MetaAuthError(
                        "threads_oauth_state",
                        "OAuth state does not match this browser session. Start the login flow again.",
                    )
                app_secret = app_secret_override or _configured_secret("THREADS_APP_SECRET")
                long_token, user_id, expires_in = ThreadsOAuthClient().exchange_code(
                    code=authorization_code,
                    app_id=app_id,
                    app_secret=app_secret,
                    redirect_uri=redirect_uri,
                )
                oauth_runtime = _runtime_env()
                active_store = EncryptedTokenStore.from_env(oauth_runtime, base_dir=ROOT)
                record = ThreadsTokenManager(
                    env=oauth_runtime,
                    store=active_store,
                ).save_long_lived_token(
                    credential_ref,
                    access_token=long_token,
                    expires_in=expires_in,
                    user_id=user_id,
                )
                st.session_state[f"runtime_secret_{credential_ref}"] = record.access_token
                st.session_state[f"runtime_expiry_{credential_ref}"] = record.expires_at.isoformat()
                st.session_state[state_key] = token_urlsafe(24)
                st.query_params.clear()
                _set_notice(
                    "success",
                    f"Threads connected · User ID `{user_id}` · expires `{record.expires_at:%Y-%m-%d}`.",
                )
                st.rerun()
            except MetaAuthError as exc:
                st.error(f"Threads OAuth failed ({exc.code}): {exc}")


def _invalidate_snapshot_download() -> None:
    st.session_state.pop("snapshot_download_bundle", None)


def _snapshot_signature(database: Path, runs: list[dict[str, object]]) -> str:
    run_state = "|".join(
        f"{run.get('run_id')}:{run.get('state')}:{run.get('workflow_state')}:{run.get('updated_at')}"
        for run in runs
    )
    return f"{database.resolve()}::{run_state}"


def _snapshot_download_bundle(
    store: SQLiteRunStore,
    database: Path,
    runs: list[dict[str, object]],
) -> dict[str, object]:
    signature = _snapshot_signature(database, runs)
    current = st.session_state.get("snapshot_download_bundle")
    if current and current.get("signature") == signature:
        return current
    data = store.backup_bytes()
    saved = save_rotating_snapshot(
        data,
        database.parent / "snapshots",
        limit=20,
    )
    bundle = {
        "signature": signature,
        "name": saved.name,
        "data": data,
    }
    st.session_state["snapshot_download_bundle"] = bundle
    return bundle


def _render_connection_results() -> None:
    results = st.session_state.get("connection_probe_results", [])
    if not results:
        return
    for result in results:
        status = str(result["status"])
        icon = "✅" if status == "ready" else "⚠️" if status in {"rate_limited"} else "❌"
        st.caption(
            f"{icon} **{str(result['role']).title()}** · `{result['provider']}` · "
            f"`{result['model']}` · {result['message']} ({result['latency_ms']} ms)"
        )


def _render_snapshot_import(database: Path) -> None:
    st.info(
        "Advanced handoff only: import runs created by CLI or GitHub Actions. This does not generate content."
    )
    uploaded_snapshot = st.file_uploader(
        "Upload a non-empty SQLite snapshot",
        type=("sqlite3", "sqlite", "db"),
        key="snapshot_upload",
        help="Do not upload Markdown, Word files, API keys, or an empty database.",
    )
    if st.button(
        "Load SQLite snapshot",
        disabled=uploaded_snapshot is None,
        width="stretch",
    ):
        try:
            summary = install_sqlite_snapshot(
                uploaded_snapshot.getvalue(),
                database,
                require_runs=True,
            )
            _invalidate_snapshot_download()
            level = "success" if summary["human_review"] else "warning"
            _set_notice(
                level,
                f"Snapshot loaded: {summary['runs']} run(s), {summary['human_review']} waiting for approval.",
            )
            st.rerun()
        except (ValueError, OSError, sqlite3.DatabaseError) as exc:
            st.error(str(exc))


def _set_review_result(
    *,
    action: str,
    level: str,
    title: str,
    message: str,
    run_id: str,
    draft_id: str,
    state: str,
    actor: str,
) -> None:
    st.session_state["review_action_result"] = {
        "action": action,
        "level": level,
        "title": title,
        "message": message,
        "run_id": run_id,
        "draft_id": draft_id,
        "state": state,
        "actor": actor,
    }


def _show_review_result(database: Path) -> None:
    result = st.session_state.get("review_action_result")
    if not result:
        return
    with st.container(border=True):
        renderer = {
            "success": st.success,
            "warning": st.warning,
            "error": st.error,
            "info": st.info,
        }.get(result["level"], st.info)
        renderer(f"{result['title']}: {result['message']}")
        columns = st.columns(4)
        columns[0].metric("Action", result["action"])
        columns[1].metric("New state", result["state"])
        columns[2].metric("Run", result["run_id"][:8])
        columns[3].metric("Operator", result["actor"] or "Unknown")
        st.caption(f"Run ID: `{result['run_id']}` · Draft ID: `{result['draft_id']}`")
        if result["action"] == "approve" and result["level"] == "success":
            st.markdown("**Next step:** open **3 · Publish** and run a dry-run first.")
            st.code(
                f"python run.py --publish-approved {result['run_id']} "
                f'--database "{database}" --publish-mode dry-run',
                language="powershell",
            )
        if st.button("Dismiss latest result", key="dismiss_review_result"):
            st.session_state.pop("review_action_result", None)
            st.rerun()


def _show_generation_result(store: SQLiteRunStore) -> None:
    result = st.session_state.get("generation_result")
    if not result:
        return
    run_id = result["run_id"]
    try:
        draft = store.get_current_draft(run_id)
        request = store.get_content_request(run_id)
        workflow = store.get_workflow(run_id)
        critic = store.get_latest_critic(run_id)
    except (KeyError, ValueError):
        st.session_state.pop("generation_result", None)
        return
    origin = "AI generation" if request.mode == ContentMode.GENERATE else "Markdown import"
    st.success(
        f"{origin} completed · state `{workflow['state']}` · "
        f"score `{critic.score if critic else 'not scored'}`"
    )
    st.text_area(
        "Generated post" if request.mode == ContentMode.GENERATE else "Imported final post",
        value=render_post(draft),
        height=210,
        disabled=True,
        key=f"generated_post_{run_id}",
    )
    st.caption(
        f"Topic: **{request.topic}** · Mode: `{request.mode.value}` · "
        f"Task: `{request.task.value}` · Source: `{request.source_type.value}`"
    )
    with st.expander("View the exact input used for this post"):
        st.write(f"**Operator instructions:** {request.instructions or 'None'}")
        if request.source_content:
            st.text_area(
                "Source content",
                value=request.source_content,
                height=180,
                disabled=True,
                key=f"generated_source_{run_id}",
            )
        else:
            st.write("No source content; the post was created from the topic and policy.")
    st.caption(f"Run ID: `{run_id}` · Request ID: `{request.request_id}` · Draft ID: `{draft.draft_id}`")
    if workflow["state"] == "human_review":
        st.info("The post is waiting in **2 · Review & approve**.")
    elif workflow["state"] in {"approved", "dry_run"}:
        st.info("The post is ready in **3 · Publish**.")


def _publish_result_panel() -> None:
    result = st.session_state.get("publish_result")
    if not result:
        return
    renderer = st.success if result["status"] in {"published", "dry_run"} else st.warning
    renderer(
        f"Publish result: `{result['status']}` · destination `{result['destination']}` · {result['reason']}"
    )
    st.caption(
        f"Publish ID: `{result['publish_id']}` · Remote post: `{result.get('remote_post_id') or 'none'}`"
    )


load_dotenv(ROOT / ".env", override=False)
_inject_styles()
database_path = _database_path()

with st.sidebar:
    st.title("✨ Content Studio")
    st.caption("Nhập ý tưởng, để AI viết và kiểm tra bài, sau đó duyệt trước khi đăng.")
    operator_identity = st.text_input(
        "Tên hoặc email người vận hành",
        value=st.session_state.get("operator_identity", ""),
        key="operator_identity",
        placeholder="Ví dụ: FanTek hoặc boss@company.com",
        help="Được lưu trong lịch sử khi approve, reject hoặc edit.",
    )

    with st.expander(
        "🔑 Kết nối AI",
        expanded=bool(_missing_provider_credentials()),
    ):
        st.caption(
            "Có thể để trống để dùng key mặc định của hệ thống. Key nhập tay chỉ "
            "ghi đè trong phiên này và không lưu vào Markdown hoặc SQLite."
        )
        for credential, label in PROVIDER_CREDENTIALS.items():
            manual_value = st.text_input(
                label,
                type="password",
                key=f"runtime_secret_{credential}",
                placeholder=(
                    "Không bắt buộc · đang dùng key hệ thống"
                    if _configured_secret(credential)
                    else "Dán API key tạm thời"
                ),
                help=f"Để trống để dùng system setting `{credential}`.",
            )
            if manual_value.strip():
                status_text = "✅ Đang dùng key nhập tay"
            elif _configured_secret(credential):
                status_text = "✅ Key mặc định hệ thống đang hoạt động"
            else:
                status_text = "⚠️ Chưa có key"
            st.markdown(
                f'<span class="status-chip">{status_text}</span>',
                unsafe_allow_html=True,
            )

        if st.button(
            "Kiểm tra 3 kết nối",
            type="primary",
            width="stretch",
            help="Kiểm tra key, endpoint và model mà không tạo content.",
        ):
            with st.spinner("Checking provider endpoints…"):
                results = probe_all_connections(env=_runtime_env())
            st.session_state["connection_probe_results"] = [
                result.model_dump(mode="json") for result in results
            ]
            if all(result.ready for result in results):
                _set_notice("success", "Cả ba kết nối AI đều sẵn sàng.")
            else:
                _set_notice(
                    "error",
                    "Có ít nhất một kết nối chưa sẵn sàng. Mở Kết nối AI để xem chi tiết.",
                )
            st.rerun()
        st.button(
            "Xóa key nhập tay",
            width="stretch",
            help="Quay lại dùng key mặc định của hệ thống.",
            on_click=_clear_manual_credentials,
        )
        _render_connection_results()

try:
    store = SQLiteRunStore(database_path)
except Exception as exc:
    st.error(f"The SQLite operations store could not start ({type(exc).__name__}).")
    st.stop()

review_service = ReviewService(store, publish_on_approve=False)
catalog, policy_errors = _policy_catalog()
runs = store.list_runs()
queue = store.list_review_queue()
usage = store.usage_summary()
snapshot_bundle = _snapshot_download_bundle(store, database_path, runs)

with st.sidebar:
    with st.expander(
        "🌐 Facebook & Threads",
        expanded=False,
    ):
        _render_social_connections(catalog)
    st.divider()
    st.caption(f"Database · `{database_path.name}`")
    st.success(f"{len(runs)} runs · {len(queue)} waiting for review")
    st.download_button(
        "Download unique SQLite snapshot",
        data=snapshot_bundle["data"],
        file_name=str(snapshot_bundle["name"]),
        mime="application/vnd.sqlite3",
        width="stretch",
        on_click=_invalidate_snapshot_download,
        key="sidebar_snapshot_download",
    )
    st.caption("Random collision-safe name · newest 20 snapshots retained locally.")
    st.caption("Need help or import? Open **5 · Analytics → Data transfer**.")

st.markdown(
    """
    <section class="hero">
      <h1>Social Content Agent Studio</h1>
      <p>Chọn kênh và upload một content Markdown. AI có thể tự research, viết,
      kiểm tra; hoặc nhập thẳng bài hoàn chỉnh vào luồng duyệt và publish.</p>
    </section>
    <div class="flow">
      <div class="flow-step"><b>Bước 1</b>Kết nối AI</div>
      <div class="flow-step"><b>Bước 2</b>Chọn kênh</div>
      <div class="flow-step"><b>Bước 3</b>Upload content .md</div>
      <div class="flow-step"><b>Bước 4</b>AI viết & tự chấm</div>
      <div class="flow-step"><b>Bước 5</b>Người thật duyệt</div>
      <div class="flow-step"><b>Bước 6</b>Publish một click</div>
    </div>
    """,
    unsafe_allow_html=True,
)
_show_notice()
_show_review_result(database_path)

metric_columns = st.columns(4)
metric_columns[0].metric("All runs", len(runs))
metric_columns[1].metric("Waiting for review", len(queue))
metric_columns[2].metric(
    "Ready to publish",
    sum(1 for run in runs if run.get("workflow_state") in {"approved", "dry_run"}),
)
metric_columns[3].metric(
    "Published",
    sum(1 for run in runs if run.get("workflow_state") == "published"),
)

create_tab, review_tab, publish_tab, accounts_tab, analytics_tab, help_tab = st.tabs(
    [
        "1 · Create content",
        "2 · Review & approve",
        "3 · Publish",
        "4 · Accounts & policies",
        "5 · Analytics",
        "6 · Help & testing",
    ]
)

with create_tab:
    st.header("Markdown Content Studio")
    st.markdown(
        """
        <div class="composer-intro">
          <strong>Một file Markdown cho toàn bộ nội dung.</strong>
          Chọn kênh, upload một file <code>.md</code>, kiểm tra preview rồi chạy.
          <b>mode: generate</b> gọi AI; <b>mode: publish</b> nhập bài hoàn chỉnh
          vào luồng duyệt mà không gọi AI.
        </div>
        """,
        unsafe_allow_html=True,
    )
    left, right = st.columns([1.7, 1], gap="large")
    with left:
        if not catalog:
            st.error(
                "Chưa có kênh/phong cách hợp lệ. Hãy cấu hình tại "
                "**4 · Accounts & policies** trước khi upload content."
            )
        else:
            selected_account = st.selectbox(
                "Kênh & phong cách",
                options=list(catalog),
                format_func=lambda account_id: (
                    f"{catalog[account_id][1].platform} · {account_id} · "
                    f"{catalog[account_id][1].tone}"
                ),
                help=(
                    "Account policy vẫn tách riêng để người dùng không bao giờ đặt token "
                    "hoặc mật khẩu trong content Markdown."
                ),
            )
            content_upload = st.file_uploader(
                "Upload content Markdown *",
                type=("md", "markdown"),
                accept_multiple_files=False,
                key="content_markdown_upload",
                help="Một file UTF-8, tối đa 100 KB. Không upload token, API key hoặc cookie.",
            )
            parsed_document = None
            if content_upload is not None:
                try:
                    parsed_document = parse_content_markdown(
                        content_upload.getvalue(),
                        source_name=content_upload.name,
                    )
                    st.success(
                        f"Markdown hợp lệ · `{parsed_document.mode.value}` · "
                        f"`{parsed_document.task.value}` · pipeline `{parsed_document.pipeline}`"
                    )
                    summary_columns = st.columns(3)
                    summary_columns[0].metric("Mode", parsed_document.mode.value)
                    summary_columns[1].metric("Task", parsed_document.task.value)
                    summary_columns[2].metric("Blocks", len(parsed_document.block_types))
                    st.write(f"**Topic:** {parsed_document.topic}")
                    preview = (
                        parsed_document.final_content
                        if parsed_document.mode == ContentMode.PUBLISH
                        else parsed_document.source_content or parsed_document.instructions
                    )
                    st.text_area(
                        "Nội dung đã parse",
                        value=preview,
                        height=220,
                        disabled=True,
                        key="parsed_markdown_preview",
                    )
                    with st.expander("Chi tiết cấu trúc Markdown"):
                        st.json(dict(metadata_summary(parsed_document)))
                        if "image" in parsed_document.block_types:
                            st.warning(
                                "Image Markdown được giữ trong cấu trúc nhưng adapter text hiện tại "
                                "chưa upload binary image lên Meta."
                            )
                except ContentMarkdownError as exc:
                    st.error(f"Markdown không hợp lệ: {exc}")

            process_markdown = st.button(
                "Chạy content Markdown",
                type="primary",
                width="stretch",
                disabled=parsed_document is None,
                help="Generate sẽ gọi AI; Publish sẽ nhập bài hoàn chỉnh vào review queue.",
            )
            if process_markdown and parsed_document is not None:
                try:
                    policy_path = catalog[selected_account][0]
                    if parsed_document.mode == ContentMode.GENERATE:
                        missing = _missing_provider_credentials()
                        if missing:
                            raise ValueError(
                                "Missing AI credentials: "
                                + ", ".join(missing)
                                + ". Dán key tạm trong Kết nối AI hoặc cấu hình key hệ thống."
                            )
                        runtime = _runtime_env()

                        def provider_factory(role, **kwargs):
                            return create_role_provider(role, env=runtime, **kwargs)

                        with st.spinner("AI đang research, viết, kiểm tra policy và chấm điểm…"):
                            result = PipelineOrchestrator(
                                store,
                                provider_factory=provider_factory,
                                publisher=PolicyPublisherRouter(
                                    store,
                                    mode="dry-run",
                                    env=runtime,
                                ),
                            ).run(
                                request=parsed_document.to_content_request(),
                                policy_path=policy_path,
                                mode=PipelineMode(parsed_document.pipeline),
                            )
                        run_id = result.run_id
                        state = result.workflow_state.value
                        message = (
                            f"AI đã tạo content cho {result.policy.account_id}; "
                            f"trạng thái `{state}`."
                        )
                    else:
                        with st.spinner("Đang kiểm tra policy và tạo bản nháp có audit…"):
                            imported = import_publish_document(
                                store,
                                policy_path=policy_path,
                                document=parsed_document,
                            )
                        run_id = imported.run_id
                        state = imported.workflow_state.value
                        message = (
                            f"Đã nhập bài hoàn chỉnh cho {imported.policy.account_id}; "
                            f"trạng thái `{state}`."
                        )
                        if not imported.hard_rule_passed:
                            message += " Bài có hard-rule violation và bắt buộc phải sửa trong Review."
                    st.session_state["generation_result"] = {"run_id": str(run_id)}
                    _set_notice("success", message)
                    _invalidate_snapshot_download()
                    st.rerun()
                except PipelineRunError as exc:
                    if exc.code == "network":
                        st.error(
                            f"Không kết nối được AI provider sau ba lần thử. Run `{exc.run_id}` "
                            "đã được lưu. Mở **Kết nối AI → Kiểm tra 3 kết nối** và kiểm tra "
                            "internet/proxy/firewall."
                        )
                    elif exc.code in {"authentication", "permission_denied"}:
                        st.error(
                            f"Provider từ chối credential hoặc permission. Run `{exc.run_id}` "
                            "đã được lưu. Hãy cập nhật key rồi kiểm tra kết nối."
                        )
                    else:
                        st.error(
                            f"Generation failed at `{exc.step.value}` ({exc.code}). "
                            f"Run `{exc.run_id}` is saved for investigation: {exc}"
                        )
                except (ContentMarkdownError, PolicyParseError, ValueError, RuntimeError) as exc:
                    st.error(str(exc))
    with right:
        st.markdown(
            """
            <div class="hint-card">
              <strong>1 · Chọn đúng template</strong><br>
              Dùng <code>generate</code> khi muốn AI viết từ topic/brief/source.
              Dùng <code>publish</code> khi file đã chứa bài hoàn chỉnh.
            </div>
            <div class="hint-card">
              <strong>2 · Không đặt secret trong file</strong><br>
              Markdown chỉ chứa nội dung. Facebook/Threads token luôn nằm trong
              system settings hoặc ô password của phiên hiện tại.
            </div>
            """,
            unsafe_allow_html=True,
        )
        template_columns = st.columns(2)
        template_columns[0].download_button(
            "Tải template Generate",
            data=GENERATE_TEMPLATE,
            file_name="content-generate.md",
            mime="text/markdown",
            width="stretch",
        )
        template_columns[1].download_button(
            "Tải template Publish",
            data=PUBLISH_TEMPLATE,
            file_name="content-publish.md",
            mime="text/markdown",
            width="stretch",
        )
        st.markdown("**Khi mode là Generate**")
        for role in (Role.RESEARCH, Role.COPYWRITER, Role.CRITIC):
            route = DEFAULT_ROUTES[role]
            source = _credential_source(route.credential_env)
            ready = "✅" if source != "missing" else "⚠️"
            selected_model = route.selected_model(_runtime_env())
            st.write(
                f"{ready} **{role.value.title()}** · {route.provider} · `{selected_model}` · key: `{source}`"
            )
        st.caption(
            "Mode Publish không tiêu tốn AI token. Cả hai mode vẫn đi qua policy, "
            "review, permission và idempotent publisher."
        )
    _show_generation_result(store)

with review_tab:
    st.header("Human review queue")
    st.caption("Approve, reject, or edit the current revision. Every action is auditable.")
    if not queue:
        st.info(
            "No posts are waiting. Generate one in **1 · Create content** using a policy with "
            "`approval_required: true`."
        )
    else:
        labels = {
            row["run_id"]: (
                f"{row['account_id']} · score {row.get('score', 'n/a')} · "
                f"{row['topic'][:55]} · {row['run_id'][:8]}"
            )
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
        content_request = store.get_content_request(selected_run)
        policy = store.get_policy(selected_run)
        critic = store.get_latest_critic(selected_run)

        left, right = st.columns([1.65, 1], gap="large")
        with left:
            st.subheader("Post preview")
            st.caption(
                f"Account `{policy.account_id}` · {policy.platform} · Publisher `{policy.publishing.adapter}`"
            )
            with st.expander("Original content request", expanded=True):
                st.write(f"**Topic:** {content_request.topic}")
                st.write(f"**Task:** `{content_request.task.value}`")
                st.write(f"**Writing brief:** {content_request.instructions or 'No extra instructions'}")
                if content_request.source_content:
                    source_label = content_request.source_name or "Pasted content"
                    st.text_area(
                        f"Source · {source_label}",
                        value=content_request.source_content,
                        height=150,
                        disabled=True,
                        key=f"review_source_{selected_run}",
                    )
                else:
                    st.write("**Source content:** None — created from topic and policy.")
            st.text_area(
                "Current post",
                value=render_post(draft),
                height=240,
                disabled=True,
            )
            st.download_button(
                "Download post as Markdown",
                data=render_post(draft),
                file_name=f"{policy.account_id}-{selected_run[:8]}.md",
                mime="text/markdown",
            )
        with right:
            st.metric("Critic score", critic.score if critic else "Unavailable")
            st.metric("Pass threshold", policy.threshold)
            st.metric("AI rewrites", item["rewrite_count"])
            if critic:
                st.markdown("**Violations**")
                st.write(critic.violations or ["None"])
                st.markdown("**Suggestions**")
                st.write(critic.suggestions or ["None"])
            if item.get("last_error_code"):
                st.warning(f"{item['last_error_code']}: {item['last_error_message']}")

        action_tabs = st.tabs(["Approve", "Edit", "Reject", "Audit trail"])
        with action_tabs[0]:
            with st.form("approve_form"):
                actor = st.text_input(
                    "Operator",
                    value=operator_identity,
                    key="approve_actor",
                )
                note = st.text_area(
                    "Approval note (required)",
                    placeholder="Example: Checked claims, tone, CTA, and policy constraints.",
                    key="approve_note",
                )
                submitted = st.form_submit_button(
                    "Approve and move to Publish",
                    type="primary",
                    width="stretch",
                )
                if submitted:
                    try:
                        review_service.approve(
                            selected_run,
                            actor=actor,
                            note=note,
                            expected_version=int(item["version"]),
                        )
                        updated = store.get_workflow(selected_run)
                        _set_review_result(
                            action="approve",
                            level="success",
                            title="Approved successfully",
                            message="The approval is audited and the post is ready for dry-run.",
                            run_id=str(selected_run),
                            draft_id=str(draft.draft_id),
                            state=str(updated["state"]),
                            actor=actor.strip(),
                        )
                        st.rerun()
                    except (ValueError, KeyError, RuntimeError) as exc:
                        st.error(f"Approval failed: {exc}")
        with action_tabs[1]:
            with st.form("edit_form"):
                actor = st.text_input(
                    "Operator",
                    value=operator_identity,
                    key="edit_actor",
                )
                edited_content = st.text_area(
                    "Edited post content",
                    value=draft.content,
                    height=200,
                )
                note = st.text_area(
                    "Edit note",
                    placeholder="Explain what changed and why.",
                    key="edit_note",
                )
                submitted = st.form_submit_button("Save as a new revision", width="stretch")
                if submitted:
                    try:
                        edited = review_service.edit(
                            selected_run,
                            actor=actor,
                            content=edited_content,
                            note=note,
                            expected_version=int(item["version"]),
                        )
                        updated = store.get_workflow(selected_run)
                        _set_review_result(
                            action="edit",
                            level="success",
                            title="Edit saved",
                            message="A new immutable revision was created; approval is still required.",
                            run_id=str(selected_run),
                            draft_id=str(edited.draft_id),
                            state=str(updated["state"]),
                            actor=actor.strip(),
                        )
                        st.rerun()
                    except (ValueError, KeyError, RuntimeError) as exc:
                        st.error(f"Edit failed: {exc}")
        with action_tabs[2]:
            with st.form("reject_form"):
                actor = st.text_input(
                    "Operator",
                    value=operator_identity,
                    key="reject_actor",
                )
                note = st.text_area(
                    "Rejection reason",
                    placeholder="Explain why this post must not publish.",
                    key="reject_note",
                )
                submitted = st.form_submit_button("Reject and close publisher guard", width="stretch")
                if submitted:
                    try:
                        updated = review_service.reject(
                            selected_run,
                            actor=actor,
                            note=note,
                            expected_version=int(item["version"]),
                        )
                        _set_review_result(
                            action="reject",
                            level="success",
                            title="Rejected",
                            message="The publisher guard remains closed.",
                            run_id=str(selected_run),
                            draft_id=str(draft.draft_id),
                            state=str(updated["state"]),
                            actor=actor.strip(),
                        )
                        st.rerun()
                    except (ValueError, KeyError, RuntimeError) as exc:
                        st.error(f"Rejection failed: {exc}")
        with action_tabs[3]:
            st.dataframe(
                store.get_review_actions(selected_run),
                width="stretch",
                hide_index=True,
            )
            st.dataframe(store.get_events(selected_run), width="stretch", hide_index=True)

with publish_tab:
    st.header("Publish")
    st.caption(
        "No file upload is needed here. The publisher sends the approved draft already stored "
        "in SQLite. Dry-run is recommended but optional; Publish sends immediately."
    )
    _publish_result_panel()
    eligible = [run for run in runs if run.get("workflow_state") in {"passed", "approved", "dry_run"}]
    if not eligible:
        st.info("No approved post is ready. Approve a post in **2 · Review & approve** first.")
    else:
        publish_run = st.selectbox(
            "Approved post",
            options=[run["run_id"] for run in eligible],
            format_func=lambda run_id: next(
                f"{run['account_id']} · {run['topic'][:60]} · {run.get('workflow_state')} · {run_id[:8]}"
                for run in eligible
                if run["run_id"] == run_id
            ),
            key="publish_run",
        )
        publish_policy = store.get_policy(publish_run)
        publish_request = store.get_content_request(publish_run)
        publish_draft = store.get_current_draft(publish_run)
        st.caption(
            f"Topic: {publish_request.topic} · task `{publish_request.task.value}` · "
            f"source `{publish_request.source_type.value}`"
        )
        st.text_area(
            "Post to deliver",
            value=render_post(publish_draft),
            height=200,
            disabled=True,
            key="publish_preview",
        )
        destination = f"{publish_policy.publishing.adapter}:{publish_policy.publishing.target_id or 'mock'}"
        st.write(
            f"**Destination:** `{destination}` · "
            f"**Credential reference:** `{publish_policy.publishing.credential_ref or 'none'}`"
        )
        dry_column, live_column = st.columns(2, gap="large")
        with dry_column:
            st.subheader("Optional safety check")
            st.caption("Dry-run does not resolve the Meta token and does not call Meta.")
            if st.button(
                "Run publishing dry-run",
                type="primary",
                width="stretch",
                key="publish_dry_run",
            ):
                try:
                    with st.spinner("Validating destination and delivery guard…"):
                        receipt = PolicyPublisherRouter(
                            store,
                            mode="dry-run",
                            env=_runtime_env(),
                        ).publish(publish_run)
                    st.session_state["publish_result"] = receipt.model_dump(mode="json")
                    st.rerun()
                except (PublishError, ValueError, KeyError) as exc:
                    st.error(f"Dry-run failed: {exc}")
        with live_column:
            st.subheader("Publish immediately")
            st.warning("Clicking Publish can create a real external post immediately.")
            credential_ref = publish_policy.publishing.credential_ref
            session_token = ""
            if credential_ref:
                session_token = st.text_input(
                    f"{credential_ref} (session only)",
                    type="password",
                    key=f"publish_token_{publish_run}",
                    placeholder=(
                        "Using secure configuration"
                        if _configured_secret(credential_ref)
                        else "Paste current Meta token"
                    ),
                )
            placeholder_target = str(publish_policy.publishing.target_id or "").startswith("000")
            if placeholder_target:
                st.warning("Live publishing is locked because this policy still has a placeholder target ID.")
            if st.button(
                "Publish live now",
                type="primary",
                width="stretch",
                disabled=placeholder_target,
                key="publish_live",
            ):
                try:
                    configured_token = (
                        session_token or _configured_secret(credential_ref) if credential_ref else ""
                    )
                    extra = {credential_ref: configured_token} if credential_ref and configured_token else {}
                    with st.spinner("Sending the approved post through the guarded publisher…"):
                        receipt = PolicyPublisherRouter(
                            store,
                            mode="live",
                            credential_resolver=(
                                EnvironmentCredentialResolver(extra)
                                if session_token and credential_ref
                                else None
                            ),
                            env=_runtime_env(extra),
                        ).publish(publish_run)
                    st.session_state["publish_result"] = receipt.model_dump(mode="json")
                    st.rerun()
                except (PublishError, ValueError, KeyError) as exc:
                    st.error(f"Live publishing failed: {exc}")
        st.subheader("Delivery receipts")
        st.dataframe(
            store.get_publish_attempts(publish_run),
            width="stretch",
            hide_index=True,
        )

with accounts_tab:
    st.header("Kênh & phong cách content")
    st.markdown(
        """
        <div class="composer-intro">
          <strong>Người dùng bình thường chỉ cần điền form.</strong>
          Hệ thống sẽ tự tạo cấu hình account ở phía sau. Markdown chỉ dành cho
          admin muốn import, review hoặc chỉnh cấu hình nâng cao.
        </div>
        """,
        unsafe_allow_html=True,
    )
    if policy_errors:
        for error in policy_errors:
            st.error(error)
    existing_tab, builder_tab, upload_tab = st.tabs(
        ["Kênh hiện có", "Tạo kênh bằng form", "Markdown nâng cao"]
    )
    with existing_tab:
        if catalog:
            st.dataframe(
                [
                    {
                        "account_id": account_id,
                        "platform": policy.platform,
                        "tone": policy.tone,
                        "active": policy.active,
                        "publisher": policy.publishing.adapter,
                        "approval_required": policy.publishing.approval_required,
                        "file": path.name,
                    }
                    for account_id, (path, policy) in catalog.items()
                ],
                width="stretch",
                hide_index=True,
            )
            inspect_account = st.selectbox(
                "Chọn kênh để xem",
                options=list(catalog),
                key="inspect_policy",
            )
            inspect_path, inspect_policy = catalog[inspect_account]
            st.write(f"**Audience:** {inspect_policy.audience}")
            st.write(f"**Tone:** {inspect_policy.tone}")
            st.write(f"**Goal:** {inspect_policy.goal}")
            with st.expander("Xem file Markdown phía sau (dành cho admin)"):
                st.code(inspect_path.read_text(encoding="utf-8"), language="markdown")
                st.download_button(
                    "Tải cấu hình Markdown",
                    data=inspect_path.read_bytes(),
                    file_name=inspect_path.name,
                    mime="text/markdown",
                )
        else:
            st.info("No valid policies found.")
    with builder_tab:
        st.info(
            "Điền các ô bên dưới rồi bấm tạo. Hệ thống tự sinh và kiểm tra file cấu hình; "
            "bạn không phải viết Markdown."
        )
        with st.form("policy_builder_form"):
            identity_left, identity_right = st.columns(2)
            with identity_left:
                display_name = st.text_input("Display name", value="My Social Account")
                account_id = st.text_input(
                    "Account slug",
                    value="my-social-account",
                    help="Lowercase letters, numbers, and hyphens only.",
                )
                platform = st.selectbox(
                    "Platform",
                    options=("Threads", "Facebook", "X", "LinkedIn", "Instagram"),
                )
                language = st.text_input("Language", value="Vietnamese")
            with identity_right:
                audience = st.text_area(
                    "Audience",
                    value="Small business owners and social content teams.",
                    height=90,
                )
                tone = st.text_area(
                    "Tone of voice",
                    value="Practical, friendly, trustworthy, and concise.",
                    height=90,
                )
            goal = st.text_area(
                "Goal & objectives",
                value="Help the audience apply useful ideas and encourage qualified engagement.",
                height=90,
            )
            constraints_text = st.text_area(
                "Hard constraints · one per line",
                value=(
                    "Do not promise guaranteed results.\n"
                    "Use concrete and actionable language.\n"
                    "Keep a human accountable for final publication."
                ),
                height=120,
            )
            banned_text = st.text_area(
                "Banned terms · one per line",
                value="guaranteed\nrevolutionary",
                height=90,
            )
            hashtags_text = st.text_area(
                "Required hashtags · one per line",
                value="#ResponsibleAI",
                height=90,
            )
            examples_text = st.text_area(
                "Voice examples · 2–3 posts, one per line",
                value=(
                    "Start with one useful experiment, measure the outcome, and keep a human owner.\n"
                    "Treat every AI draft as a proposal that still needs evidence and review."
                ),
                height=120,
            )
            length_col, threshold_col = st.columns(2)
            with length_col:
                max_length = st.number_input(
                    "Maximum post length",
                    min_value=1,
                    max_value=10_000,
                    value=500,
                )
            with threshold_col:
                threshold = st.slider("Critic pass threshold", 0, 100, 80)
            st.markdown("**Scoring rubric — must total 100**")
            rubric_columns = st.columns(4)
            compliance = rubric_columns[0].number_input(
                "Policy",
                min_value=0,
                max_value=100,
                value=40,
            )
            clarity = rubric_columns[1].number_input(
                "Clarity",
                min_value=0,
                max_value=100,
                value=25,
            )
            usefulness = rubric_columns[2].number_input(
                "Usefulness",
                min_value=0,
                max_value=100,
                value=25,
            )
            originality = rubric_columns[3].number_input(
                "Originality",
                min_value=0,
                max_value=100,
                value=10,
            )
            st.markdown("**Publishing configuration**")
            adapter = st.selectbox(
                "Publisher adapter",
                options=("mock", "threads", "facebook_page"),
                help="Choose mock while learning. Real adapters still require target ID and token.",
            )
            approval_required = st.checkbox(
                "Require human approval before publishing",
                value=True,
            )
            target_id = st.text_input(
                "Target ID · required for Facebook Page or Threads",
            )
            credential_ref = st.text_input(
                "Token environment variable · uppercase name only",
                placeholder="THREADS_MY_ACCOUNT_TOKEN",
            )
            topic_tag = st.text_input("Threads fallback topic/community tag")
            topic_candidates_text = st.text_area(
                "Threads tag candidates · one per line, maximum five",
                height=90,
            )
            trend_search = st.checkbox("Select the most active configured Threads tag")
            build_policy = st.form_submit_button(
                "Tạo và kiểm tra cấu hình kênh",
                type="primary",
                width="stretch",
            )
            if build_policy:
                try:
                    values = PolicyBuilderInput(
                        display_name=display_name,
                        account_id=account_id,
                        goal=goal,
                        audience=audience,
                        platform=platform,
                        tone=tone,
                        language=language,
                        constraints=split_lines(constraints_text),
                        banned_terms=split_lines(banned_text),
                        required_hashtags=split_lines(hashtags_text),
                        examples=split_lines(examples_text),
                        threshold=int(threshold),
                        max_length=int(max_length),
                        policy_compliance_weight=int(compliance),
                        clarity_weight=int(clarity),
                        usefulness_weight=int(usefulness),
                        originality_weight=int(originality),
                        adapter=adapter,
                        target_id=target_id,
                        credential_ref=credential_ref,
                        approval_required=approval_required,
                        topic_tag=topic_tag,
                        topic_tag_candidates=split_lines(topic_candidates_text),
                        trend_search=trend_search,
                    )
                    st.session_state["policy_editor"] = render_policy_markdown(values)
                    st.success("Đã tạo và kiểm tra cấu hình. Bấm lưu bên dưới để dùng ngay.")
                except (PolicyParseError, ValueError) as exc:
                    st.error(f"Không thể tạo cấu hình: {exc}")

        if "policy_editor" in st.session_state:
            st.subheader("Kiểm tra và lưu kênh")
            st.caption(
                "Nếu không phải admin, bạn chỉ cần xem phần tóm tắt và bấm lưu. "
                "Không cần mở hoặc chỉnh Markdown."
            )
            with st.expander("Chỉnh Markdown thủ công (admin nâng cao)", expanded=False):
                policy_editor = st.text_area(
                    "Policy Markdown",
                    key="policy_editor",
                    height=600,
                    help="Raw contract dành cho admin muốn chỉnh sâu.",
                )
            try:
                preview_policy = parse_policy_text(policy_editor, source="<policy-studio>")
                st.success(
                    f"Kênh hợp lệ: `{preview_policy.account_id}` · "
                    f"{preview_policy.platform} · {preview_policy.publishing.adapter}"
                )
                summary_columns = st.columns(3)
                summary_columns[0].metric("Platform", preview_policy.platform)
                summary_columns[1].metric("Ngưỡng Critic", preview_policy.threshold)
                summary_columns[2].metric(
                    "Cần duyệt",
                    "Có" if preview_policy.publishing.approval_required else "Không",
                )
                overwrite = st.checkbox(
                    "Ghi đè nếu đã có kênh cùng slug",
                    key="policy_overwrite",
                )
                save_col, download_col = st.columns(2)
                with save_col:
                    if st.button(
                        "Lưu và sử dụng kênh",
                        type="primary",
                        width="stretch",
                    ):
                        try:
                            saved_path, saved_policy = save_policy_markdown(
                                policy_editor,
                                ROOT / "accounts",
                                overwrite=overwrite,
                            )
                            _set_notice(
                                "success",
                                f"Đã lưu {saved_path.name}. Kênh `{saved_policy.account_id}` "
                                "có thể dùng ngay, không cần sửa code.",
                            )
                            st.rerun()
                        except (OSError, ValueError, FileExistsError) as exc:
                            st.error(str(exc))
                with download_col:
                    st.download_button(
                        "Tải bản cấu hình cho admin",
                        data=policy_editor,
                        file_name=f"{preview_policy.account_id}.md",
                        mime="text/markdown",
                        width="stretch",
                    )
            except PolicyParseError as exc:
                st.error(f"Markdown validation failed: {exc}")
    with upload_tab:
        st.markdown(
            "Khu vực admin: upload một **account policy `.md`** đã có. Người dùng "
            "thông thường nên quay lại tab **Tạo kênh bằng form**."
        )
        policy_upload = st.file_uploader(
            "Upload account policy Markdown",
            type=("md", "markdown"),
            key="policy_upload",
        )
        if policy_upload is not None:
            try:
                uploaded_markdown = policy_upload.getvalue().decode("utf-8")
                uploaded_policy = parse_policy_text(
                    uploaded_markdown,
                    source=policy_upload.name,
                )
                st.success(f"Valid policy `{uploaded_policy.account_id}` for {uploaded_policy.platform}.")
                st.code(uploaded_markdown, language="markdown")
                overwrite_upload = st.checkbox(
                    "Replace existing policy with the same slug",
                    key="upload_policy_overwrite",
                )
                if st.button(
                    "Save uploaded policy",
                    type="primary",
                    key="save_uploaded_policy",
                ):
                    save_policy_markdown(
                        uploaded_markdown,
                        ROOT / "accounts",
                        overwrite=overwrite_upload,
                    )
                    _set_notice(
                        "success",
                        f"Imported `{uploaded_policy.account_id}` into accounts/.",
                    )
                    st.rerun()
            except (UnicodeDecodeError, PolicyParseError, OSError, ValueError) as exc:
                st.error(f"Policy upload failed: {exc}")

with analytics_tab:
    st.header("Runs, quality, cost, and audit evidence")
    run_tab, score_tab, usage_tab, data_tab = st.tabs(
        ["Run history", "Score history", "Tokens & quota", "Data transfer"]
    )
    with run_tab:
        if not runs:
            st.info("No runs yet. Generate content in **1 · Create content**.")
        else:
            st.dataframe(runs, width="stretch", hide_index=True)
            history_run = st.selectbox(
                "Inspect run",
                options=[run["run_id"] for run in runs],
                format_func=lambda run_id: next(
                    f"{run['account_id']} · {run['topic'][:60]} · "
                    f"{run.get('workflow_state') or run['state']} · {run_id[:8]}"
                    for run in runs
                    if run["run_id"] == run_id
                ),
                key="history_run",
            )
            history_request = store.get_content_request(history_run)
            st.caption(
                f"Task `{history_request.task.value}` · source "
                f"`{history_request.source_type.value}` · request `{history_request.request_id}`"
            )
            with st.expander("Original topic, brief, and source content"):
                st.write(f"**Topic:** {history_request.topic}")
                st.write(f"**Writing brief:** {history_request.instructions or 'None'}")
                if history_request.source_content:
                    st.text_area(
                        "Stored source content",
                        value=history_request.source_content,
                        height=150,
                        disabled=True,
                        key=f"history_source_{history_run}",
                    )
                else:
                    st.write("No source content was supplied.")
            try:
                history_draft = store.get_current_draft(history_run)
            except KeyError:
                history_draft = None
            if history_draft is None:
                st.warning(
                    "This run failed before a valid draft was created. Inspect Events "
                    "for the safe error code and retry guidance."
                )
            else:
                st.text_area(
                    "Persisted post",
                    value=render_post(history_draft),
                    height=180,
                    disabled=True,
                )
            detail_tabs = st.tabs(["Events", "Revisions", "Critics", "Reviews", "Publishing", "Artifacts"])
            detail_tabs[0].dataframe(
                store.get_events(history_run),
                width="stretch",
                hide_index=True,
            )
            detail_tabs[1].json(store.get_draft_revisions(history_run))
            detail_tabs[2].json(store.get_critic_results(history_run))
            detail_tabs[3].dataframe(
                store.get_review_actions(history_run),
                width="stretch",
                hide_index=True,
            )
            detail_tabs[4].dataframe(
                store.get_publish_attempts(history_run),
                width="stretch",
                hide_index=True,
            )
            detail_tabs[5].json(store.get_artifacts(history_run))
    with score_tab:
        score_rows = store.score_history()
        if score_rows:
            score_frame = pd.DataFrame(score_rows)
            score_frame["created_at"] = pd.to_datetime(score_frame["created_at"])
            st.line_chart(score_frame, x="created_at", y="score", color="account_id")
            st.dataframe(score_frame, width="stretch", hide_index=True)
        else:
            st.info("No Critic scores yet.")
    with usage_tab:
        if usage["by_run"]:
            st.subheader("Per post/account")
            st.dataframe(usage["by_run"], width="stretch", hide_index=True)
        else:
            st.info("No provider usage yet.")
        if usage["by_provider"]:
            st.subheader("Per provider/model")
            st.dataframe(usage["by_provider"], width="stretch", hide_index=True)
        st.json(usage["total"])
    with data_tab:
        st.subheader("Collision-safe SQLite snapshots")
        st.write(
            "The application uses **one canonical operational database** so runs and approvals "
            "stay consistent. Downloads receive a timestamp plus random suffix; the local "
            "rotation retains at most 20 snapshots."
        )
        snapshot_directory = database_path.parent / "snapshots"
        retained = (
            len(list(snapshot_directory.glob("content-agent-*.sqlite3")))
            if snapshot_directory.exists()
            else 0
        )
        st.metric("Retained local snapshots", retained)
        st.code(str(snapshot_bundle["name"]))
        st.download_button(
            "Download prepared unique snapshot",
            data=snapshot_bundle["data"],
            file_name=str(snapshot_bundle["name"]),
            mime="application/vnd.sqlite3",
            width="stretch",
            on_click=_invalidate_snapshot_download,
            key="analytics_snapshot_download",
        )
        st.divider()
        st.subheader("Import a run snapshot")
        _render_snapshot_import(database_path)

with help_tab:
    st.header("How to test the complete system")
    st.markdown(
        """
        ### The normal user journey

        1. Open **Kết nối AI** in the sidebar. Leave the password fields blank
           to use `.env`/Streamlit Secrets, or paste a session-only override.
           Click **Kiểm tra 3 kết nối** before generating.
        2. Open **1 · Create content**, download a Generate or Publish template,
           and put the complete request/post in that one UTF-8 Markdown file.
        3. Choose a channel, upload the `.md`, verify the parsed preview, and
           click **Chạy content Markdown**.
        4. Research → Copywriter → rule Critic → LLM Critic run automatically.
           Failed AI drafts are rewritten no more than twice. `mode: publish`
           imports a manual draft without calling AI.
        5. Open **2 · Review & approve** to inspect score, violations, suggestions,
           edit the post, and approve it with an audit note.
        6. Open **3 · Publish**. Dry-run is optional. If the platform token and
           target ID are real, **Publish live now** sends immediately without a
           typed confirmation phrase.
        7. A new channel can be created in **4 · Accounts & policies → Tạo kênh
           bằng form**. Markdown import/editing is an advanced admin option only.

        ### What gets uploaded where?

        | Place | Upload/input | Purpose |
        |---|---|---|
        | Create content | One UTF-8 `.md`/`.markdown` | Topic + brief + source, or final post |
        | Accounts → Guided form | Normal form fields | Add/change a channel without Markdown |
        | Accounts → Markdown | `.md` account policy | Advanced admin import |
        | Analytics → Data transfer | Non-empty SQLite snapshot | Move run evidence from Actions |
        | Kết nối AI | Optional API key in password field | Manual override; blank uses system default |
        | Publish | Nothing | Sends the approved draft already stored in SQLite |

        ### Safety rules

        - Start with `mock` publishing while learning.
        - Facebook live publishing targets a managed **Page**, not a personal/clone login.
        - Never place API keys, passwords, cookies, or tokens in any Markdown.
        - Source content is stored with the run for review lineage and is treated
          as untrusted data, not as hidden agent instructions.
        - `approval_required: true` keeps every passing draft in the human queue.
        - Dry-run cannot create an external Meta post.
        - Live Publish is one click, but backend workflow/permission/credential/
          target/idempotency guards remain mandatory.
        - Threads tokens can refresh silently before expiry when encrypted token
          storage is configured; an already-expired token requires OAuth reconnect.
        - The operational store is one canonical SQLite database. Each download
          gets a random unique filename; at most 20 local snapshots are retained.
        """
    )
    st.subheader("CLI equivalents for repeatable testing")
    st.code(
        """python run.py --list-accounts
python run.py --account responsible-ai-lab --topic "Campaign topic" --instructions "Use a practical checklist"
python run.py --account responsible-ai-lab --topic "Campaign topic" `
  --content-file source.md --content-task repurpose
python run.py --publish-approved RUN_ID --publish-mode dry-run
python -m pytest -q""",
        language="powershell",
    )
    st.subheader("Markdown policy anatomy")
    st.write(
        "Required sections: Account, Goal, Audience, Platform, Tone, Language, "
        "Constraints, Examples, Rubric, Threshold, Maximum Length, and Model Route. "
        "Publishing is optional and defaults to mock."
    )
    st.download_button(
        "Download blank policy template",
        data=(ROOT / "accounts" / "template.md").read_bytes(),
        file_name="account-policy-template.md",
        mime="text/markdown",
    )
