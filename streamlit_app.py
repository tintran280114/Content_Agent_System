"""Guided end-to-end social content studio and operations dashboard."""

from __future__ import annotations

import os
import html as html_lib
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
from content_agent.linkedin_auth import (
    LinkedInAuthError,
    LinkedInOAuthClient,
    LinkedInTokenManager,
    build_linkedin_authorization_url,
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
    page_title="Content Operations",
    page_icon=str(ROOT / "assets" / "content-ops-mark.png"),
    layout="wide",
    initial_sidebar_state="expanded",
)

PROVIDER_CREDENTIALS = {
    "GEMINI_API_KEY": "Gemini · Research",
    "GROQ_API_KEY": "Groq · Copywriter & Critic",
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
          --ink: #14213d;
          --muted: #667085;
          --brand: #0f766e;
          --brand-2: #14213d;
          --panel: #ffffff;
        }
        .stApp {
          background: #f3f5f7;
        }
        .block-container {
          max-width: 1240px;
          padding-top: 2.2rem;
          padding-bottom: 3rem;
        }
        .workspace-header {
          display:block;
          margin:0 0 .65rem;
          padding:1.15rem 1.3rem 1.2rem;
          background:#ffffff;
          border:1px solid #d7dce2;
          border-left:4px solid #0f766e;
          border-radius:6px;
          box-shadow:0 2px 8px rgba(20,33,61,.04);
        }
        .workspace-header h1 {
          color:#14213d;
          font-size:1.55rem;
          line-height:1.2;
          letter-spacing:-.025em;
          margin:.2rem 0 0;
        }
        .workspace-header p { color:#667085; margin:.45rem 0 0; font-size:.92rem; }
        .eyebrow { color:#0f766e; font-size:.68rem; font-weight:800; letter-spacing:.12em; }
        [data-testid="stSidebar"] {
          background: #14213d;
          border-right: 1px solid #243555;
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
          border-radius: 4px;
        }
        [data-testid="stSidebar"] button {
          color: #172033 !important;
          background: #f8fafc;
          border: 1px solid rgba(148,163,184,.42);
          border-radius: 4px;
          font-weight: 700;
        }
        [data-testid="stSidebar"] button p {
          color: inherit !important;
        }
        [data-testid="stSidebar"] button[kind="primary"] {
          color: #ffffff !important;
          background: #0f766e;
          border: 0;
        }
        [data-testid="stSidebar"] details {
          background: rgba(255,255,255,.055);
          border: 1px solid rgba(148,163,184,.16);
          border-radius: 4px;
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
          border-radius: 6px;
          padding: 1.6rem 1.8rem;
          color: white;
          background: #14213d;
          border-left: 6px solid #0f766e;
          box-shadow: 0 8px 20px rgba(20,33,61,.12);
          margin-bottom: 1rem;
        }
        .hero h1 { margin: 0 0 .35rem; font-size: 2rem; letter-spacing: -.025em; }
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
          border-radius: 4px;
          padding: .72rem .8rem;
          box-shadow: none;
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
          border-radius: 4px;
          padding: .8rem 1rem;
          box-shadow: none;
        }
        [data-testid="stTabs"] {
          background:#ffffff;
          border:1px solid #d7dce2;
          border-radius:6px;
          padding:0 .45rem;
          margin-bottom:1rem;
        }
        [data-testid="stTabs"] button { font-weight:650; padding:.72rem .9rem; }
        div[data-testid="stForm"] {
          background: rgba(255,255,255,.72);
          border: 1px solid rgba(148,163,184,.25);
          border-radius: 6px;
          padding: 1.15rem;
          box-shadow: none;
        }
        .hint-card {
          border-left: 4px solid var(--brand);
          background: rgba(255,255,255,.82);
          border-radius: 4px;
          padding: .9rem 1rem;
          margin: .5rem 0;
        }
        .composer-intro {
          border: 1px solid rgba(109,93,252,.2);
          background: #edf7f5;
          border-radius: 4px;
          padding: 1rem 1.15rem;
          margin: .4rem 0 1rem;
        }
        .composer-intro strong {
          display: block;
          color: #0f5f59;
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
        .channel-card, .analytics-channel, .help-card {
          background:#ffffff;
          border:1px solid #d7dce2;
          border-top:5px solid var(--platform, #0f766e);
          border-radius:8px;
          padding:1rem 1.05rem;
          box-shadow:0 7px 18px rgba(20,33,61,.08);
        }
        .channel-card { min-height:154px; margin:.25rem 0 .8rem; }
        .analytics-channel { min-height:116px; margin:.15rem 0 .85rem; }
        .help-card { min-height:142px; margin:.15rem 0 .75rem; }
        .platform-title {
          display:flex;
          align-items:center;
          gap:.65rem;
          color:#14213d;
          font-weight:800;
          margin-bottom:.65rem;
        }
        .platform-mark {
          display:inline-flex;
          align-items:center;
          justify-content:center;
          width:2rem;
          height:2rem;
          border-radius:6px;
          color:#ffffff;
          background:var(--platform, #0f766e);
          font-weight:900;
          font-size:.82rem;
        }
        .card-kicker { color:#667085; font-size:.76rem; font-weight:700; text-transform:uppercase; letter-spacing:.06em; }
        .card-value { color:#14213d; font-size:1.35rem; font-weight:800; margin:.15rem 0; }
        .card-copy { color:#667085; font-size:.84rem; line-height:1.45; margin:0; }
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
    manual = str(
        st.session_state.get(f"runtime_secret_{key}", "")
        or st.session_state.get(f"manual_token_input_{key}", "")
        or ""
    ).strip()
    if manual:
        return "manual"
    if _configured_secret(key):
        return "system"
    return "missing"


def _runtime_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    runtime = dict(os.environ)
    for credential in (*PROVIDER_CREDENTIALS, *META_CONFIGURATION):
        override = (
            st.session_state.get(f"runtime_secret_{credential}", "")
            or st.session_state.get(f"manual_token_input_{credential}", "")
            or ""
        ).strip()
        value = override or _configured_secret(credential)
        if value:
            runtime[credential] = value
    for key, raw_value in st.session_state.items():
        if key.startswith("runtime_secret_") and str(raw_value or "").strip():
            runtime[key.removeprefix("runtime_secret_")] = str(raw_value).strip()
        if key.startswith("manual_token_input_") and str(raw_value or "").strip():
            credential_ref = key.removeprefix("manual_token_input_")
            if credential_ref not in runtime and str(raw_value).strip():
                runtime[credential_ref] = str(raw_value).strip()
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
        "message": "Session keys cleared. The workspace is using system configuration.",
    }


def _render_threads_post_card(
    account_id: str,
    platform: str,
    topic_tag: str | None,
    content: str,
    *,
    timestamp: str = "1 min",
) -> None:
    """Render a platform-aware social post preview without changing delivery data."""
    platform_key = platform.strip().casefold()
    is_threads = platform_key == "threads"
    themes = {
        "facebook": ("#1877f2", "f", "#ffffff", "#1c1e21", "#65676b", "#d8dadf", "Like · Comment · Share"),
        "linkedin": ("#0a66c2", "in", "#ffffff", "#191919", "#666666", "#d6d6d6", "Like · Comment · Repost · Send"),
        "threads": ("#101010", "@", "#101010", "#f5f5f5", "#a1a1aa", "#2a2a2a", "Like · Reply · Repost · Share"),
    }
    brand, mark, background, text_color, muted, border, actions = themes.get(
        platform_key, themes["linkedin"]
    )
    if is_threads and topic_tag and topic_tag.strip():
        clean_tag = topic_tag.strip().removeprefix("#")
        tag_html = (
            f'<span style="display: inline-flex; align-items: center; gap: 5px; background: #162638; '
            f'border: 1px solid #254160; color: #38bdf8; font-weight: 700; padding: 3px 11px; border-radius: 14px; '
            f'font-size: 13px; margin-left: 6px; box-shadow: 0 2px 8px rgba(56, 189, 248, 0.15);">'
            f'<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">'
            f'<circle cx="12" cy="6" r="2.5"/><circle cx="6" cy="16" r="2.5"/><circle cx="18" cy="16" r="2.5"/>'
            f'</svg>'
            f'{clean_tag}'
            f'</span>'
        )
    elif is_threads:
        tag_html = (
            '<span style="display: inline-flex; align-items: center; color: #8e8e93; font-size: 12px; font-style: italic; margin-left: 6px;">'
            '(No topic tag)'
            '</span>'
        )
    else:
        tag_html = ""

    formatted_content = html_lib.escape(content).replace("\n", "<br>")
    safe_account = html_lib.escape(account_id)

    card_html = (
        f'<div style="background:{background};color:{text_color};border:1px solid {border};border-top:6px solid {brand};border-radius:8px;padding:22px 24px;font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',sans-serif;margin:10px 0 22px;box-shadow:0 14px 34px rgba(20,33,61,.16);">'
        f'<div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px;">'
        f'<div style="display: flex; align-items: center; gap: 10px;">'
        f'<div style="width:42px;height:42px;border-radius:4px;background:{brand};display:flex;align-items:center;justify-content:center;font-weight:800;color:#fff;font-size:18px;">'
        f'{mark}'
        f'</div>'
        f'<div style="display: flex; align-items: center; flex-wrap: wrap; gap: 4px; font-size: 15px; font-weight: 600;">'
        f'<span style="color:{text_color};font-weight:700;">{safe_account}</span>'
        f'{tag_html}'
        f'</div>'
        f'</div>'
        f'<span style="color:{muted};font-size:13px;font-weight:500;">{timestamp}</span>'
        f'</div>'
        f'<div style="font-size:15px;line-height:1.55;color:{text_color};margin-bottom:16px;word-break:break-word;">'
        f'{formatted_content}'
        f'</div>'
        f'<div style="color:{muted};font-size:13px;font-weight:650;padding-top:12px;border-top:1px solid {border};">'
        f'{actions}'
        f'</div>'
        f'</div>'
    )
    if hasattr(st, "html"):
        st.html(card_html)
    else:
        st.markdown(card_html, unsafe_allow_html=True)


def _post_preview_heading(platform: str) -> str:
    """Return accurate UI copy for the selected publishing platform."""
    if platform.strip().casefold() == "threads":
        return "**Threads post preview:**"
    if platform.strip().casefold() == "linkedin":
        return "**LinkedIn personal post preview:**"
    return f"**{platform.strip() or 'Channel'} post preview:**"


def _platform_label(platform: str, account_id: str = "") -> str:
    """Compact platform identity suitable for native Streamlit controls."""
    marks = {
        "facebook": "🔵 f",
        "linkedin": "🟦 in",
        "threads": "⚫ @",
        "x": "⚫ 𝕏",
    }
    name = platform.strip() or "Channel"
    mark = marks.get(name.casefold(), "◼")
    return f"{mark}  {name}" + (f" · {account_id}" if account_id else "")


def _platform_theme(platform: str) -> tuple[str, str]:
    return {
        "facebook": ("#1877f2", "f"),
        "linkedin": ("#0a66c2", "in"),
        "threads": ("#111111", "@"),
        "x": ("#111827", "𝕏"),
    }.get(platform.strip().casefold(), ("#0f766e", "●"))


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
    linkedin = [
        (account_id, policy)
        for account_id, (_, policy) in catalog.items()
        if policy.publishing.adapter == "linkedin"
    ]
    st.caption(
        "Session tokens are temporary. Persistent tokens are encrypted and never stored in Markdown or SQLite."
    )
    st.markdown("**Facebook Pages**")
    if not facebook:
        st.caption("No Facebook Page account configured.")
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
        st.caption("No Threads account configured.")
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
            st.warning("Threads is not connected.")
        if not status.persistent_rotation:
            st.caption(
                "Configure `CONTENT_AGENT_TOKEN_ENCRYPTION_KEY` to persist refreshed tokens."
            )
    except MetaAuthError as exc:
        token_store = None
        manager = None
        st.error(f"Threads token store: {exc}")

    manual_token = st.text_input(
        f"{credential_ref} (session only)",
        type="password",
        key=f"manual_token_input_{credential_ref}",
        placeholder=(
            "Using secure system configuration"
            if _configured_secret(credential_ref)
            else "Paste a Threads long-lived token"
        ),
    )
    token_days = st.number_input(
        "Token validity (days)",
        min_value=1,
        max_value=60,
        value=60,
        key=f"threads_token_days_{credential_ref}",
        help="Use the exact expires_in value returned by Meta when available.",
    )
    if st.button(
        "Activate Threads token",
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
                    "Threads token encrypted and stored."
                    if active_store
                    else "Threads token activated for this browser session."
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
                    f"Threads token refreshed · expires `{record.expires_at:%Y-%m-%d}`.",
                )
                st.rerun()
            except MetaAuthError as exc:
                st.error(str(exc))

    with st.expander(
        "Threads OAuth setup",
        expanded=not bool(status and status.configured),
    ):
        st.caption(
            "Configure a Meta App with the Threads use case and an exact redirect URI. "
            "The App Secret remains server-side."
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
            "1 · Authorize Threads",
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
            help="The app reads the code after redirect; manual paste is also supported.",
        )
        if st.button(
            "3 · Connect Threads",
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

    st.markdown("**LinkedIn personal profiles**")
    if not linkedin:
        st.caption("No LinkedIn account configured.")
        return
    linkedin_account = st.selectbox(
        "LinkedIn account",
        options=[account_id for account_id, _ in linkedin],
        key="linkedin_connection_account",
    )
    linkedin_policy = next(
        policy for account_id, policy in linkedin if account_id == linkedin_account
    )
    linkedin_ref = str(linkedin_policy.publishing.credential_ref)
    linkedin_runtime = _runtime_env()
    try:
        linkedin_manager = LinkedInTokenManager.from_env(linkedin_runtime, base_dir=ROOT)
        linkedin_manager.resolve(linkedin_ref)
        st.success(f"LinkedIn token configured for `{linkedin_account}`.")
    except LinkedInAuthError as exc:
        linkedin_manager = LinkedInTokenManager.from_env(linkedin_runtime, base_dir=ROOT)
        if exc.code == "linkedin_token_expired":
            st.error(str(exc))
        else:
            st.warning("LinkedIn is not connected.")

    manual_linkedin_token = st.text_input(
        f"{linkedin_ref} (session only)",
        type="password",
        key=f"manual_token_input_{linkedin_ref}",
        placeholder="Paste a LinkedIn access token",
    )
    person_urn = st.text_input(
        "LinkedIn Person URN",
        value=(
            ""
            if "REPLACE_WITH" in str(linkedin_policy.publishing.target_id)
            else str(linkedin_policy.publishing.target_id)
        ),
        placeholder="urn:li:person:...",
        key=f"linkedin_person_urn_{linkedin_ref}",
    )
    if st.button(
        "Activate LinkedIn token",
        disabled=not bool(manual_linkedin_token.strip() and person_urn.strip()),
        key=f"save_linkedin_token_{linkedin_ref}",
        width="stretch",
    ):
        try:
            record = linkedin_manager.save(
                linkedin_ref,
                access_token=manual_linkedin_token,
                person_urn=person_urn,
                expires_in=60 * 24 * 60 * 60,
            )
            st.session_state[f"runtime_secret_{linkedin_ref}"] = record.access_token
            st.session_state[f"runtime_expiry_{linkedin_ref}"] = record.expires_at.isoformat()
            _set_notice("success", "LinkedIn token activated securely.")
            st.rerun()
        except LinkedInAuthError as exc:
            st.error(str(exc))

    with st.expander("LinkedIn OAuth setup", expanded=True):
        st.caption(
            "Requires Share on LinkedIn and Sign in with LinkedIn using OpenID Connect. "
            "Scopes: `openid profile w_member_social`."
        )
        linkedin_client_id = st.text_input(
            "LinkedIn Client ID",
            value=_configured_secret("LINKEDIN_CLIENT_ID"),
            key="linkedin_oauth_client_id",
        )
        linkedin_client_secret = st.text_input(
            "LinkedIn Client Secret",
            type="password",
            key="runtime_secret_LINKEDIN_CLIENT_SECRET",
            placeholder=(
                "Đang dùng system secret"
                if _configured_secret("LINKEDIN_CLIENT_SECRET")
                else "Dán Client Secret"
            ),
        )
        linkedin_redirect_uri = st.text_input(
            "LinkedIn OAuth Redirect URI",
            value=_configured_secret("LINKEDIN_REDIRECT_URI") or "http://localhost:8501",
            key="linkedin_oauth_redirect_uri",
        )
        linkedin_state_key = f"linkedin_oauth_state_{linkedin_ref}"
        if linkedin_state_key not in st.session_state:
            st.session_state[linkedin_state_key] = token_urlsafe(24)
        try:
            linkedin_authorization_url = build_linkedin_authorization_url(
                client_id=linkedin_client_id,
                redirect_uri=linkedin_redirect_uri,
                state=st.session_state[linkedin_state_key],
            )
        except LinkedInAuthError:
            linkedin_authorization_url = "https://www.linkedin.com/developers/apps"
        st.link_button(
            "1 · Authorize LinkedIn",
            linkedin_authorization_url,
            disabled=not bool(linkedin_client_id.strip() and linkedin_redirect_uri.strip()),
            width="stretch",
        )
        linkedin_callback_code = str(st.query_params.get("code", "") or "")
        linkedin_callback_state = str(st.query_params.get("state", "") or "")
        linkedin_code = st.text_input(
            "2 · LinkedIn authorization code",
            value=linkedin_callback_code,
            key="linkedin_oauth_code",
        )
        if st.button(
            "3 · Connect LinkedIn",
            type="primary",
            disabled=not bool(linkedin_code.strip()),
            key=f"exchange_linkedin_code_{linkedin_ref}",
            width="stretch",
        ):
            try:
                # LinkedIn can return the callback in a fresh Streamlit browser
                # session (especially through a development tunnel).  In that
                # case the operator pastes the one-time code back into the
                # initiating session and no callback state is present here.
                # Validate state whenever it is supplied; do not reject the
                # explicit manual-code path solely because it has no query
                # parameters.
                if (
                    linkedin_callback_state
                    and linkedin_callback_state != st.session_state[linkedin_state_key]
                ):
                    raise LinkedInAuthError(
                        "linkedin_oauth_state",
                        "OAuth state does not match this browser session. Start again.",
                    )
                active_secret = linkedin_client_secret or _configured_secret("LINKEDIN_CLIENT_SECRET")
                token, oauth_person_urn, expires_in = LinkedInOAuthClient().exchange_code(
                    code=linkedin_code,
                    client_id=linkedin_client_id,
                    client_secret=active_secret,
                    redirect_uri=linkedin_redirect_uri,
                )
                active_manager = LinkedInTokenManager.from_env(_runtime_env(), base_dir=ROOT)
                record = active_manager.save(
                    linkedin_ref,
                    access_token=token,
                    person_urn=oauth_person_urn,
                    expires_in=expires_in,
                )
                st.session_state[f"runtime_secret_{linkedin_ref}"] = record.access_token
                st.session_state[f"runtime_expiry_{linkedin_ref}"] = record.expires_at.isoformat()
                st.session_state[linkedin_state_key] = token_urlsafe(24)
                st.query_params.clear()
                _set_notice(
                    "success",
                    f"LinkedIn connected · Person URN `{oauth_person_urn}` · expires `{record.expires_at:%Y-%m-%d}`. "
                    "Update the account policy target_id to this Person URN before live publishing.",
                )
                st.rerun()
            except LinkedInAuthError as exc:
                st.error(f"LinkedIn OAuth failed ({exc.code}): {exc}")


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
        columns[3].metric("Audit", "Recorded")
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
        policy = store.get_policy(run_id)
    except (KeyError, ValueError):
        st.session_state.pop("generation_result", None)
        return
    origin = "AI generation" if request.mode == ContentMode.GENERATE else "Markdown import"
    st.success(
        f"{origin} completed · state `{workflow['state']}` · "
        f"score `{critic.score if critic else 'not scored'}`"
    )
    topic_tag = getattr(draft, "topic_tag", None) or policy.publishing.topic_tag or (
        policy.publishing.topic_tag_candidates[0]
        if policy.publishing.topic_tag_candidates
        else None
    )
    st.markdown(_post_preview_heading(policy.platform))
    _render_threads_post_card(
        account_id=policy.account_id,
        platform=policy.platform,
        topic_tag=topic_tag,
        content=render_post(draft),
    )
    st.text_area(
        "Generated post" if request.mode == ContentMode.GENERATE else "Imported final post",
        value=render_post(draft),
        height=180,
        disabled=True,
        key=f"generated_post_{run_id}",
    )
    st.caption(
        f"Topic: **{request.topic}** · Mode: `{request.mode.value}` · "
        f"Task: `{request.task.value}` · Source: `{request.source_type.value}`"
    )
    with st.expander("View the exact input used for this post"):
        st.write(f"**Content brief:** {request.instructions or 'None'}")
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
    if result.get("topic_tag"):
        st.info(f"**Published Threads topic tag:** `{result['topic_tag']}`")
    st.caption(
        f"Publish ID: `{result['publish_id']}` · Remote post: `{result.get('remote_post_id') or 'none'}`"
    )


load_dotenv(ROOT / ".env", override=False)
_inject_styles()
database_path = _database_path()

with st.sidebar:
    st.logo(str(ROOT / "assets" / "content-ops-mark.png"), size="large")
    st.title("Content Operations")
    st.caption("Create, review, and publish content across every connected channel.")

    with st.expander(
        "AI connections",
        expanded=bool(_missing_provider_credentials()),
    ):
        st.caption(
            "Leave fields blank to use secure system configuration. Session overrides are never stored in Markdown or SQLite."
        )
        for credential, label in PROVIDER_CREDENTIALS.items():
            manual_value = st.text_input(
                label,
                type="password",
                key=f"runtime_secret_{credential}",
                placeholder=(
                    "Using system configuration"
                    if _configured_secret(credential)
                    else "Paste a session API key"
                ),
                help=f"Leave blank to use `{credential}` from system configuration.",
            )
            if manual_value.strip():
                status_text = "Session key active"
            elif _configured_secret(credential):
                status_text = "System key active"
            else:
                status_text = "Not configured"
            st.markdown(
                f'<span class="status-chip">{status_text}</span>',
                unsafe_allow_html=True,
            )

        if st.button(
            "Test AI connections",
            type="primary",
            width="stretch",
            help="Validate credentials, endpoints, and models without generating content.",
        ):
            with st.spinner("Checking provider endpoints…"):
                results = probe_all_connections(env=_runtime_env())
            st.session_state["connection_probe_results"] = [
                result.model_dump(mode="json") for result in results
            ]
            if all(result.ready for result in results):
                _set_notice("success", "All AI connections are ready.")
            else:
                _set_notice(
                    "error",
                    "At least one AI connection is unavailable. Open AI connections for details.",
                )
            st.rerun()
        st.button(
            "Clear session keys",
            width="stretch",
            help="Return to secure system configuration.",
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


def _approve_review_and_open_publish(run_id: str, draft_id: str, version: int) -> None:
    """Approve from the one-click review gate, then select the Publish tab."""

    try:
        review_service.approve(
            run_id,
            actor="Dashboard user",
            note="Dashboard approval after a passing AI review.",
            expected_version=version,
        )
        updated = store.get_workflow(run_id)
        _set_review_result(
            action="approve",
            level="success",
            title="Approved successfully",
            message="The approval is audited and the post is ready for dry-run.",
            run_id=run_id,
            draft_id=draft_id,
            state=str(updated["state"]),
            actor="Dashboard user",
        )
        st.session_state["publish_run"] = run_id
        st.session_state["workspace_tabs"] = "Publish"
    except (ValueError, KeyError, RuntimeError) as exc:
        st.session_state["review_approval_error"] = f"Approval failed: {exc}"

with st.sidebar:
    with st.expander(
        "Channel connections",
        expanded=False,
    ):
        _render_social_connections(catalog)
    st.divider()
    st.caption(f"{len(queue)} awaiting review · {sum(1 for run in runs if run.get('workflow_state') == 'published')} published")

st.markdown(
    """
    <section class="workspace-header">
      <div><span class="eyebrow">CONTENT OPERATIONS</span><h1>Publishing workspace</h1></div>
      <p>One controlled workflow from draft to delivery.</p>
    </section>
    """,
    unsafe_allow_html=True,
)
_show_notice()
_show_review_result(database_path)

create_tab, review_tab, publish_tab, accounts_tab, analytics_tab, help_tab = st.tabs(
    [
        "Create",
        "Review",
        "Publish",
        "Channels",
        "Analytics",
        "Help",
    ],
    key="workspace_tabs",
    on_change="rerun",
)

with create_tab:
    st.header("Create content")
    st.caption("Select a channel and import one Markdown content request.")
    left, right = st.columns([2.5, 1], gap="large")
    with left:
        if not catalog:
            st.error(
                "No valid channel is configured. Add one in **4 · Channels**."
            )
        else:
            selected_account = st.selectbox(
                "Channel",
                options=list(catalog),
                format_func=lambda account_id: (
                    f"{_platform_label(catalog[account_id][1].platform, account_id)} · "
                    f"{catalog[account_id][1].tone}"
                ),
                help=(
                    "Channel policy is stored separately; never place tokens or passwords in content Markdown."
                ),
            )
            content_upload = st.file_uploader(
                "Upload content Markdown *",
                type=("md", "markdown"),
                accept_multiple_files=False,
                key="content_markdown_upload",
                help="One UTF-8 file, up to 100 KB. Never upload tokens, API keys, or cookies.",
            )
            parsed_document = None
            if content_upload is not None:
                try:
                    parsed_document = parse_content_markdown(
                        content_upload.getvalue(),
                        source_name=content_upload.name,
                    )
                    st.success(
                        f"Valid Markdown · `{parsed_document.mode.value}` · "
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
                        "Parsed content",
                        value=preview,
                        height=220,
                        disabled=True,
                        key="parsed_markdown_preview",
                    )
                    with st.expander("Markdown structure"):
                        st.json(dict(metadata_summary(parsed_document)))
                        if "image" in parsed_document.block_types:
                            st.warning(
                                "Image Markdown is preserved, but current text adapters do not upload binary media."
                            )
                except ContentMarkdownError as exc:
                    st.error(f"Invalid Markdown: {exc}")

            process_markdown = st.button(
                "Continue with Markdown",
                type="primary",
                width="stretch",
                disabled=parsed_document is None,
                help="Generate uses AI. Publish imports final copy into the review queue.",
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

                        with st.spinner("Researching, writing, and evaluating content…"):
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
                            f"Content created for {result.policy.account_id} · state `{state}`."
                        )
                    else:
                        with st.spinner("Validating policy and creating an auditable draft…"):
                            imported = import_publish_document(
                                store,
                                policy_path=policy_path,
                                document=parsed_document,
                            )
                        run_id = imported.run_id
                        state = imported.workflow_state.value
                        message = (
                            f"Final copy imported for {imported.policy.account_id} · state `{state}`."
                        )
                        if not imported.hard_rule_passed:
                            message += " Hard-rule violations must be resolved in Review."
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
        st.subheader("Templates")
        st.caption("Generate uses AI. Publish imports final copy.")
        template_columns = st.columns(2)
        template_columns[0].download_button(
            "Download Generate template",
            data=GENERATE_TEMPLATE,
            file_name="content-generate.md",
            mime="text/markdown",
            width="stretch",
        )
        template_columns[1].download_button(
            "Download Publish template",
            data=PUBLISH_TEMPLATE,
            file_name="content-publish.md",
            mime="text/markdown",
            width="stretch",
        )
        with st.expander("Format and connection details"):
            st.write("Markdown must contain front matter and content sections. Secrets are never stored in files.")
            for role in (Role.RESEARCH, Role.COPYWRITER, Role.CRITIC):
                route = DEFAULT_ROUTES[role]
                source = _credential_source(route.credential_env)
                st.caption(f"{role.value.title()} · {route.provider} · {source}")
    _show_generation_result(store)

with review_tab:
    st.header("Review")
    st.caption("Inspect the current revision and choose one action.")
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
            with st.expander("Source and brief", expanded=False):
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
            topic_tag = getattr(draft, "topic_tag", None) or policy.publishing.topic_tag or (
                policy.publishing.topic_tag_candidates[0]
                if policy.publishing.topic_tag_candidates
                else None
            )
            st.markdown(_post_preview_heading(policy.platform))
            _render_threads_post_card(
                account_id=policy.account_id,
                platform=policy.platform,
                topic_tag=topic_tag,
                content=render_post(draft),
            )
            st.text_area(
                "Current post text",
                value=render_post(draft),
                height=160,
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

        critic_passed = bool(
            critic
            and critic.rule_passed
            and critic.score >= policy.threshold
            and critic.decision.casefold() == "pass"
        )
        if critic_passed:
            st.success(
                f"AI review passed · Score {critic.score}/{policy.threshold} · "
                f"{len(critic.violations)} policy violation(s)."
            )
            if st.button(
                "Approve and continue to Publish",
                type="primary",
                width="stretch",
                key="approve_and_continue",
                on_click=_approve_review_and_open_publish,
                args=(str(selected_run), str(draft.draft_id), int(item["version"])),
            ):
                pass
            approval_error = st.session_state.pop("review_approval_error", None)
            if approval_error:
                st.error(approval_error)
        else:
            score_text = f"{critic.score}/{policy.threshold}" if critic else "unavailable"
            st.warning(
                f"AI review is not ready for approval · Score {score_text}. "
                "Edit, reject, or generate a revised post before publishing."
            )

        with st.expander("More actions", expanded=False):
            edit_tab, reject_tab, audit_tab = st.tabs(["Edit", "Reject", "Audit trail"])
            with edit_tab:
                with st.form("edit_form"):
                    edited_content = st.text_area(
                        "Edited post content",
                        value=draft.content,
                        height=200,
                    )
                    edited_topic_tag = st.text_input(
                        "Threads topic tag",
                        value=getattr(draft, "topic_tag", "") or policy.publishing.topic_tag or "",
                        key=f"edit_topic_tag_{selected_run}",
                        help="Optional topic tag displayed beside the Threads username.",
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
                                actor="Dashboard user",
                                content=edited_content,
                                topic_tag=edited_topic_tag,
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
                                actor="Dashboard user",
                            )
                            st.rerun()
                        except (ValueError, KeyError, RuntimeError) as exc:
                            st.error(f"Edit failed: {exc}")
            with reject_tab:
                with st.form("reject_form"):
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
                                actor="Dashboard user",
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
                                actor="Dashboard user",
                            )
                            st.rerun()
                        except (ValueError, KeyError, RuntimeError) as exc:
                            st.error(f"Rejection failed: {exc}")
            with audit_tab:
                st.dataframe(
                    store.get_review_actions(selected_run),
                    width="stretch",
                    hide_index=True,
                )
                st.dataframe(store.get_events(selected_run), width="stretch", hide_index=True)

with publish_tab:
    st.header("Publish")
    st.caption("Choose an approved post, validate the destination, and deliver.")
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
        publish_topic_tag = getattr(publish_draft, "topic_tag", None) or publish_policy.publishing.topic_tag or (
            publish_policy.publishing.topic_tag_candidates[0]
            if publish_policy.publishing.topic_tag_candidates
            else None
        )
        st.markdown(_post_preview_heading(publish_policy.platform))
        _render_threads_post_card(
            account_id=publish_policy.account_id,
            platform=publish_policy.platform,
            topic_tag=publish_topic_tag,
            content=render_post(publish_draft),
        )
        st.text_area(
            "Post text to deliver",
            value=render_post(publish_draft),
            height=160,
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
            st.caption("Dry-run does not resolve the platform token or call an external API.")
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
            st.subheader("Publish live")
            st.caption("The approved post will be sent to the selected external account.")
            credential_ref = publish_policy.publishing.credential_ref
            session_token = ""
            if credential_ref:
                session_token = st.text_input(
                    f"Optional {credential_ref} override",
                    type="password",
                    key=f"publish_token_{publish_run}",
                    placeholder=(
                        "Using secure configuration"
                        if _configured_secret(credential_ref)
                        else "Paste current platform token"
                    ),
                    help=(
                        "Leave blank to use the secure token from .env. A pasted token replaces it "
                        "only for this browser session and is not saved to .env, Markdown, or SQLite. "
                        "Facebook requires a Page Access Token, not a User Access Token."
                    ),
                )
            raw_target = str(publish_policy.publishing.target_id or "")
            placeholder_target = raw_target.startswith("000") or "REPLACE_WITH" in raw_target
            if placeholder_target:
                st.warning("Live publishing is locked because this policy still has a placeholder target ID.")
            live_confirmed = st.checkbox(
                "I confirm the account, content, and destination are correct.",
                value=False,
                key=f"publish_confirmation_{publish_run}",
            )
            if st.button(
                "Publish now",
                type="primary",
                width="stretch",
                disabled=placeholder_target or not live_confirmed,
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
        with st.expander("Delivery receipts"):
            st.dataframe(
                store.get_publish_attempts(publish_run),
                width="stretch",
                hide_index=True,
            )

with accounts_tab:
    st.header("Channels")
    st.caption("Manage publishing destinations and content rules.")
    if policy_errors:
        for error in policy_errors:
            st.error(error)
    existing_tab, builder_tab, upload_tab = st.tabs(
        ["Current channels", "Add channel", "Advanced Markdown"], key="channel_tabs"
    )
    with existing_tab:
        if catalog:
            channel_items = list(catalog.items())
            for offset in range(0, len(channel_items), 3):
                channel_columns = st.columns(3)
                for column, (account_id, (_, policy)) in zip(
                    channel_columns, channel_items[offset : offset + 3]
                ):
                    color, mark = _platform_theme(policy.platform)
                    state = "Active" if policy.active else "Paused"
                    column.markdown(
                        f"""
                        <div class="channel-card" style="--platform:{color}">
                          <div class="platform-title"><span class="platform-mark">{mark}</span>
                            <span>{html_lib.escape(account_id)}</span></div>
                          <div class="card-kicker">{html_lib.escape(policy.platform)} · {state}</div>
                          <p class="card-copy">{html_lib.escape(policy.tone)}</p>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
            inspect_account = st.selectbox(
                "Select channel",
                options=list(catalog),
                format_func=lambda account_id: _platform_label(
                    catalog[account_id][1].platform, account_id
                ),
                key="inspect_policy",
            )
            inspect_path, inspect_policy = catalog[inspect_account]
            st.write(f"**Audience:** {inspect_policy.audience}")
            st.write(f"**Tone:** {inspect_policy.tone}")
            st.write(f"**Goal:** {inspect_policy.goal}")
            with st.expander("View policy Markdown"):
                st.code(inspect_path.read_text(encoding="utf-8"), language="markdown")
                st.download_button(
                    "Download policy",
                    data=inspect_path.read_bytes(),
                    file_name=inspect_path.name,
                    mime="text/markdown",
                )
            with st.expander("Channel inventory"):
                st.dataframe(
                    [
                        {
                            "account_id": account_id,
                            "platform": policy.platform,
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
        else:
            st.info("No valid policies found.")
    with builder_tab:
        st.info(
            "Complete the form to generate and validate a channel policy."
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
                    options=("Facebook", "Threads", "LinkedIn"),
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
            adapter = {
                "Facebook": "facebook_page",
                "Threads": "threads",
                "LinkedIn": "linkedin",
            }[platform]
            st.caption(f"{platform} publishing is configured automatically.")
            approval_required = st.checkbox(
                "Require human approval before publishing",
                value=True,
            )
            target_id = st.text_input(
                {
                    "Facebook": "Facebook Page ID",
                    "Threads": "Threads User ID",
                    "LinkedIn": "LinkedIn Person URN",
                }[platform],
            )
            credential_ref = st.text_input(
                "Token environment variable · uppercase name only",
                placeholder=f"{platform.upper()}_MY_ACCOUNT_TOKEN",
            )
            if platform == "Threads":
                topic_tag = st.text_input("Fallback topic tag")
                topic_candidates_text = st.text_area(
                    "Topic tag candidates · one per line, maximum five",
                    height=90,
                )
                trend_search = st.checkbox("Select the most active configured topic tag")
            else:
                topic_tag = ""
                topic_candidates_text = ""
                trend_search = False
            build_policy = st.form_submit_button(
                "Generate channel configuration",
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
                    st.success("Channel configuration generated and validated.")
                except (PolicyParseError, ValueError) as exc:
                    st.error(f"Could not generate channel configuration: {exc}")

        if "policy_editor" in st.session_state:
            st.subheader("Review and save channel")
            st.caption(
                "Review the summary and save. Markdown editing is optional and intended for administrators."
            )
            with st.expander("Edit policy Markdown", expanded=False):
                policy_editor = st.text_area(
                    "Policy Markdown",
                    key="policy_editor",
                    height=600,
                    help="Advanced policy contract editing.",
                )
            try:
                preview_policy = parse_policy_text(policy_editor, source="<policy-studio>")
                st.success(
                    f"Valid channel: `{preview_policy.account_id}` · "
                    f"{preview_policy.platform} · {preview_policy.publishing.adapter}"
                )
                summary_columns = st.columns(3)
                summary_columns[0].metric("Platform", preview_policy.platform)
                summary_columns[1].metric("Critic threshold", preview_policy.threshold)
                summary_columns[2].metric(
                    "Approval",
                    "Required" if preview_policy.publishing.approval_required else "Not required",
                )
                overwrite = st.checkbox(
                    "Replace an existing channel with the same slug",
                    key="policy_overwrite",
                )
                save_col, download_col = st.columns(2)
                with save_col:
                    if st.button(
                        "Save channel",
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
                                f"Saved {saved_path.name}. Channel `{saved_policy.account_id}` is ready.",
                            )
                            st.rerun()
                        except (OSError, ValueError, FileExistsError) as exc:
                            st.error(str(exc))
                with download_col:
                    st.download_button(
                        "Download configuration",
                        data=policy_editor,
                        file_name=f"{preview_policy.account_id}.md",
                        mime="text/markdown",
                        width="stretch",
                    )
            except PolicyParseError as exc:
                st.error(f"Markdown validation failed: {exc}")
    with upload_tab:
        st.markdown(
            "Administrator area: import an existing account policy `.md` file."
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
    st.header("Analytics")
    st.caption("Monitor workflow activity and channel readiness at a glance.")
    platform_activity: dict[str, dict[str, int]] = {}
    for account_id, (_, policy) in catalog.items():
        summary = platform_activity.setdefault(policy.platform, {"channels": 0, "runs": 0})
        summary["channels"] += 1
        summary["runs"] += sum(1 for run in runs if run.get("account_id") == account_id)
    if platform_activity:
        activity_columns = st.columns(min(4, len(platform_activity)))
        for column, (platform, summary) in zip(
            activity_columns, sorted(platform_activity.items())
        ):
            color, mark = _platform_theme(platform)
            column.markdown(
                f"""
                <div class="analytics-channel" style="--platform:{color}">
                  <div class="platform-title"><span class="platform-mark">{mark}</span>
                    <span>{html_lib.escape(platform)}</span></div>
                  <div class="card-value">{summary['runs']} runs</div>
                  <p class="card-copy">{summary['channels']} configured channel(s)</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
    analytics_metrics = st.columns(4)
    analytics_metrics[0].metric("Runs", len(runs))
    analytics_metrics[1].metric("In review", len(queue))
    analytics_metrics[2].metric("Ready", sum(1 for run in runs if run.get("workflow_state") in {"approved", "dry_run"}))
    analytics_metrics[3].metric("Published", sum(1 for run in runs if run.get("workflow_state") == "published"))
    run_tab, score_tab, usage_tab, data_tab = st.tabs(
        ["Run history", "Score history", "Tokens & quota", "Data transfer"],
        key="analytics_tabs",
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
            detail_tabs = st.tabs(
                ["Events", "Revisions", "Critics", "Reviews", "Publishing", "Artifacts"],
                key="analytics_detail_tabs",
            )
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
    st.header("Help center")
    st.caption("A concise guide for creating, approving, and safely publishing content.")
    help_columns = st.columns(3)
    for column, number, title, copy in (
        (help_columns[0], "01", "Create", "Choose a channel and upload one UTF-8 Markdown request."),
        (help_columns[1], "02", "Review", "Check the final copy, record a decision, and approve it."),
        (help_columns[2], "03", "Publish", "Validate with dry-run, then confirm the live destination."),
    ):
        column.markdown(
            f"""
            <div class="help-card">
              <div class="card-kicker">Step {number}</div>
              <div class="card-value">{title}</div>
              <p class="card-copy">{copy}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

    quick_tab, connection_tab, safety_tab, admin_tab = st.tabs(
        ["Quick start", "Connections", "Safe publishing", "Admin tools"], key="help_tabs"
    )
    with quick_tab:
        st.markdown(
            """
            1. In **Create**, select the destination and upload a Generate or Publish template.
            2. Confirm the parsed preview. Generate uses AI; Publish imports finished copy.
            3. In **Review**, inspect the content and approve it.
            4. In **Publish**, run a dry-run, verify the destination, and publish when ready.
            """
        )
        st.info("Publish reads the approved draft from SQLite. No second upload is required.")
    with connection_tab:
        st.markdown(
            """
            - Open **AI connections** only for AI-assisted generation.
            - Open **Channel connections** to connect Facebook, Threads, or LinkedIn.
            - Blank password fields use secure system configuration; typed keys are session-only.
            - LinkedIn live publishing requires a valid member token and person URN.
            """
        )
    with safety_tab:
        st.markdown(
            """
            - Never place tokens, passwords, cookies, or client secrets in Markdown.
            - Use dry-run before the first live delivery to every new destination.
            - Facebook targets a managed Page; LinkedIn currently targets a personal profile.
            - Human approval, permission checks, idempotency, and audit records remain mandatory.
            - Reconnect OAuth when a token is expired and cannot be refreshed.
            """
        )
    with admin_tab:
        with st.expander("CLI commands"):
            st.code(
                """python run.py --list-accounts
python run.py --account responsible-ai-lab --topic "Campaign topic"
python run.py --publish-approved RUN_ID --publish-mode dry-run
python -m pytest -q""",
                language="powershell",
            )
        with st.expander("Policy Markdown reference"):
            st.write(
                "A policy defines the account, platform, audience, tone, constraints, "
                "quality threshold, model route, and publishing adapter."
            )
            st.download_button(
                "Download blank policy template",
                data=(ROOT / "accounts" / "template.md").read_bytes(),
                file_name="account-policy-template.md",
                mime="text/markdown",
            )
