# Social Content Agent System — Wednesday MVP

A CLI-first, scheduled social-content batch pipeline with a Streamlit operations
dashboard. The system wakes up for a few minutes, generates and evaluates posts,
persists traceable state in SQLite, and routes unsafe output to human review.
It does not need FastAPI, React, authentication, or a 24/7 application server.

```text
Markdown policy
  → Gemini Research
  → Groq Copywriter
  → deterministic Rule Critic
  → GitHub Models LLM Critic
  → pass / at most two Groq rewrites / human review
  → guarded mock Publisher
  → SQLite + Streamlit
```

## MVP capabilities

- Add accounts with versioned Markdown only; three differentiated policies and
  a template are included.
- Run one account with `--account` or every account with `--all`.
- Preserve the Day 1 Policy → Research → Copywriter mode.
- Run the full hybrid-Critic workflow with strict provider separation.
- Retry safe 429/timeout/provider failures with bounded exponential backoff.
- Enforce a maximum of two AI rewrites; terminal failures enter human review.
- Approve, reject, or edit through Streamlit with persisted audit events.
- Mock-publish only Critic-passed or explicitly human-approved content.
- Inspect queues, scores, histories, tokens, costs, revisions, and errors.
- Run twice daily or manually through GitHub Actions.
- Resume the fixed 10-topic × three-policy evaluation after interruption.
- Deploy the dashboard on Streamlit Community Cloud without a backend API.

## Quick start on Windows Command Prompt

```cmd
cd /d D:\Fantek_material\AI_AgentSystem\Content_Agent_System
py -3.11 -m venv .venv
.venv\Scripts\activate.bat
python -m pip install -r requirements.txt
copy .env.example .env
```

Do not overwrite an existing `.env`. Fill the local file with your own
free-tier credentials:

```dotenv
GEMINI_API_KEY=
GEMINI_MODEL=gemini-3.1-flash-lite
GROQ_API_KEY=
GROQ_MODEL=llama-3.3-70b-versatile
GITHUB_MODELS_TOKEN=
GITHUB_MODELS_MODEL=openai/gpt-4o-mini
```

Never commit `.env` or `.streamlit/secrets.toml`.

## Offline verification

These commands consume no provider quota:

```cmd
python run.py --help
python run.py --list-accounts
python scripts\provider_spike.py --dry-run
python scripts\evaluate.py --help
python -m unittest discover -s tests -v
```

## CLI batch pipeline

Day 1 compatible draft-only run:

```cmd
python run.py --account responsible-ai-lab --topic "Responsible AI for small teams" --database artifacts\content_agent.sqlite3
```

Full safety/review pipeline:

```cmd
python run.py --account responsible-ai-lab --pipeline full --topic "Responsible AI for small teams" --database artifacts\content_agent.sqlite3
```

All three policies (`--all` defaults to the full pipeline):

```cmd
python run.py --all --topic "Responsible AI for small teams" --database artifacts\content_agent.sqlite3
```

A successful full run ends as `published` through the local mock Publisher. A
draft that still fails after two rewrites ends as `human_review`. A Critic or
rewrite provider failure after a valid draft exists also fails safe into the
queue; it is never auto-published.

## Streamlit dashboard

```cmd
streamlit run streamlit_app.py
```

Open `http://localhost:8501`. The dashboard reads and writes the same SQLite
database and provides:

- latest runs and workflow states;
- real human-review queue and Critic details;
- approve/reject/edit actions with operator, note, time, and revision audit;
- Critic score history and provider token/cost summaries;
- SQLite snapshot upload/download for GitHub Actions and Community Cloud.

Set another database in the sidebar or with:

```cmd
set CONTENT_AGENT_DB=artifacts\content_agent.sqlite3
streamlit run streamlit_app.py
```

## Fixed 30-output evaluation

This makes live provider calls. Results are saved after every case, so the same
command resumes completed work:

```cmd
python scripts\evaluate.py --evaluation-id wednesday-v1 --database artifacts\evaluation.sqlite3 --output artifacts\evaluation_report.json
```

Use `--limit 1` for a one-case smoke test. Use `--no-resume` only when you
intentionally want new runs for already-completed cases.

## Scheduled automation

`.github/workflows/batch.yml` has manual dispatch and two daily schedules at
08:17 and 20:17 in `Asia/Ho_Chi_Minh`. Add `GEMINI_API_KEY`, `GROQ_API_KEY`, and
`GITHUB_MODELS_TOKEN` as GitHub Actions repository secrets. Each run uploads the
SQLite database and evidence under a 14-day workflow artifact.

Scheduled workflows run only after the workflow exists on the repository's
default branch. GitHub notes that schedules may be delayed under load, so this
is a batch cadence rather than a precise real-time SLA.

## Deploy on Streamlit Community Cloud

1. Push/merge the release branch to GitHub.
2. At [share.streamlit.io](https://share.streamlit.io), select **Create app**.
3. Choose the repository, branch, and root entrypoint `streamlit_app.py`.
4. In Advanced settings choose Python 3.11.
5. Paste `.streamlit/secrets.toml.example` into Secrets after filling values.
6. Deploy, then upload the latest SQLite artifact in the dashboard sidebar.

Community Cloud initializes apps from the repository root and installs the
pinned `streamlit==1.59.2` from `requirements.txt`. Real secrets belong in the
Cloud Secrets console, never Git. See
[`docs/deployment_streamlit.md`](docs/deployment_streamlit.md) for the exact
handoff and storage limitation.

## Add account 4 without Python changes

```cmd
copy accounts\template.md accounts\account-4.md
python run.py --list-accounts
python run.py --account account-4 --pipeline full --topic "Your topic"
```

Edit only `accounts/account-4.md`; Git provides the policy version history.

## Project structure

```text
.github/workflows/       CI and twice-daily/manual batch automation
.streamlit/              dashboard theme and safe secrets template
accounts/                Markdown policies and account template
evaluation/              frozen ten-topic evaluation set
streamlit_app.py         only interactive UI surface
run.py                   one-account and --all batch CLI
scripts/evaluate.py      resumable 30-case evaluation
src/content_agent/ai/    providers, agents, prompts, schemas
src/content_agent/       critics, orchestration, review, publisher, policy
src/content_agent/platform/ SQLite schema, events, usage, audit queries
tests/                   offline unit, resilience, E2E, UI, security tests
```

## Safety boundary

- The Publisher is a mock; no real social network API is called.
- Rule violations cannot be waived by the LLM Critic.
- Copywriter/rewriter uses Groq; Critic uses GitHub Models.
- AI rewrite count cannot exceed two.
- Failed/rejected/human-review states are blocked from publishing.
- Human approval requires an audit note; edits create immutable revisions.
- Runtime artifacts and credentials are ignored by Git.

Known limitations and deferred production work are documented in
[`docs/known_limitations.md`](docs/known_limitations.md). Day 1 live evidence is
preserved in [`docs/evidence/day1_g1_live_2026-07-22.md`](docs/evidence/day1_g1_live_2026-07-22.md).
