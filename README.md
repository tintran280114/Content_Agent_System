# Social Content Agent System - Wednesday MVP

CLI-first scheduled social-content pipeline with embedded SQLite and a
review-only Streamlit dashboard. The system wakes up for a bounded batch, saves
all decisions and usage, then exits. It does not need FastAPI, React, an
always-on server, or an external database.

```text
Markdown AccountPolicy
  -> Gemini Research
  -> Groq Copywriter
  -> local Rule Critic
  -> GitHub Models LLM Critic
  -> pass / at most two Groq rewrites / human review
  -> guarded Mock Publisher
  -> SQLite -> Streamlit review dashboard
```

## Implemented scope

- One canonical `PipelineOrchestrator` used by draft and full CLI modes.
- Three differentiated Markdown policies plus an account template.
- Three separate LLM providers with structured contracts and metadata.
- Hybrid deterministic/LLM Critic, maximum two AI rewrites, and fail-safe review.
- Bounded retry/backoff and application-side daily request/token quotas.
- Swappable `Publisher` interface with a guarded `MockPublisher` implementation.
- SQLite runs, events, revisions, scores, review audit, usage, and publish receipts.
- CLI `--account`, `--all`, draft compatibility, cron/Actions scheduling.
- Streamlit queue, approve/reject/edit, history, score, token, cost, and retry views.
- Resumable 10-topic x 3-policy evaluation with raw-output comparisons.

The sprint documents define a demo-ready Wednesday MVP. Real social publishing,
authentication/RBAC, multi-tenancy, a cloud database, and a full web application
are intentionally outside this release.

## Setup on Windows Command Prompt

```cmd
cd /d D:\Fantek_material\AI_AgentSystem\Content_Agent_System
py -3.11 -m venv .venv
.venv\Scripts\activate.bat
python -m pip install -r requirements.txt
copy .env.example .env
```

Fill `.env` with your own `GEMINI_API_KEY`, `GROQ_API_KEY`, and
`GITHUB_MODELS_TOKEN`. Never commit `.env`. Quota limits are also configurable
in that file.

Offline checks do not call providers:

```cmd
python run.py --help
python run.py --list-accounts
python scripts\provider_spike.py --dry-run
python -m unittest discover -s tests -v
```

## Run the batch pipeline

One account through the full pipeline:

```cmd
python run.py --account responsible-ai-lab --topic "Responsible AI for small teams"
```

Every configured account:

```cmd
python run.py --all --topic "Responsible AI for small teams"
```

Day 1 draft-only compatibility:

```cmd
python run.py --account responsible-ai-lab --pipeline draft --topic "Responsible AI for small teams"
```

The default database is `artifacts/content_agent.sqlite3`. Full runs either
mock-publish a safe post or leave it in `human_review`; rejected, failed, and
unapproved content cannot publish. Exit code `4` means the batch stopped before
the next account because a provider/application quota was exhausted.

## Run the review dashboard

Run the CLI first, then start Streamlit against the same SQLite file:

```cmd
streamlit run streamlit_app.py
```

Open `http://localhost:8501`. Streamlit does not generate content and does not
need LLM secrets. It provides:

- current run and human-review queues;
- approve, reject, and immutable edit actions with operator audit;
- run events, artifacts, revisions, and mock-publish decisions;
- score history plus token/cost/request/retry metrics per run and provider;
- consistent SQLite evidence download.

## Scheduled GitHub Actions batch

`.github/workflows/batch.yml` supports manual dispatch and runs at 08:17 and
20:17 in `Asia/Ho_Chi_Minh`. Add the three provider credentials as repository
Actions Secrets. Scheduled workflows only run after this workflow is on the
repository default branch.

The workflow restores the most recent non-expired `content-agent-latest`
artifact when possible, runs all accounts, and uploads the resulting SQLite
snapshot. Artifacts are a bounded evidence handoff, not a durable database.

## Streamlit Community Cloud

Deploy the root file `streamlit_app.py` with Python 3.11. No Streamlit LLM
Secrets are required. Because Community Cloud local files are only
semi-persistent and its machine is separate from GitHub Actions:

1. download `content-agent-latest` from the latest Actions run;
2. expand the artifact and upload `content_agent.sqlite3` in the dashboard's
   **Cloud snapshot handoff** panel;
3. perform human review;
4. download the reviewed SQLite evidence before a reboot or redeploy.

See [Streamlit deployment](docs/deployment_streamlit.md).

## Fixed 30-case evaluation

This makes live provider calls and checkpoints each case so it can resume:

```cmd
python scripts\evaluate.py --evaluation-id wednesday-v1
```

Use `--limit 1` for a smoke run. The JSON report includes raw outputs,
same-topic policy comparisons, score/state summaries per account, token/cost,
request/retry rate, and provider/model/prompt/SDK versions. Do not claim the
evaluation complete until it reports 30 completed cases.

## Add account 4 without Python changes

```cmd
copy accounts\template.md accounts\account-4.md
python run.py --list-accounts
python run.py --account account-4 --topic "Your topic"
```

Edit only the Markdown policy; Git supplies its version history.

## Project map

```text
.github/workflows/          offline CI and twice-daily batch automation
accounts/                   Markdown policies and account template
evaluation/                 fixed ten-topic evaluation set
run.py                      only content-generation entrypoint
streamlit_app.py            review-only interactive surface
scripts/evaluate.py         resumable 30-case evaluation
src/content_agent/          orchestrator, agents, quota, review, publisher
src/content_agent/platform/ SQLite schema, event log, usage, audit queries
tests/                      offline contracts, integration, UI, safety tests
```

## Safety boundary

- No social-network API is called; publishing is mocked.
- Hard policy violations cannot be waived by the LLM or a reviewer.
- Copywriter/rewriter and Critic use different providers.
- Provider retries do not consume the two-rewrite content budget.
- Every failure has a normalized code and persisted event trail.
- Provider keys stay in local environment variables or Actions Secrets.

Read [architecture](docs/architecture.md),
[known limitations](docs/known_limitations.md), and
[release evidence](docs/day2_day3_evidence.md).
