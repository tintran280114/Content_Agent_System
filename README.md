# Social Content Agent System

Policy-driven social-content pipeline with a guided Streamlit studio, CLI batch
automation, and embedded SQLite evidence. A non-technical operator can create
an account policy, upload one content Markdown file, generate a post with three
AI providers or import a publish-ready post, review/approve it, and publish from
one UI. The same canonical orchestrator powers AI generation in the UI, CLI,
and scheduled batch.

```text
Markdown AccountPolicy + Content Markdown -> ContentRequest
  -> Gemini Research
  -> Groq Copywriter
  -> local Rule Critic
  -> GitHub Models LLM Critic
  -> pass / at most two Groq rewrites / human review
  -> guarded policy-selected Publisher (mock / Facebook Page / Threads)
  -> SQLite -> guided Streamlit create/review/publish studio
```

## Implemented scope

- One canonical `PipelineOrchestrator` used by draft and full CLI modes.
- Three differentiated Facebook, Threads, and X policies plus an account template.
- Three separate LLM providers with structured contracts and metadata.
- Hybrid deterministic/LLM Critic, maximum two AI rewrites, and fail-safe review.
- Bounded retry/backoff and application-side daily request/token quotas.
- Mock, Facebook Page, and Threads publishers with dry-run and explicit live gates.
- Threads topic tags with optional recent-activity selection from up to five niche candidates.
- Encrypted Threads token storage, OAuth exchange, proactive refresh, publish
  reservations, retry/backoff, and remote post IDs.
- Session-only manual AI-key overrides with system-default fallback and safe connection probes.
- SQLite runs, events, revisions, scores, review audit, usage, and publish receipts.
- Collision-safe SQLite download names with a bounded 20-snapshot local rotation.
- CLI `--account`, `--all`, draft compatibility, cron/Actions scheduling.
- One-file content Markdown contract with `generate` and `publish` modes.
- Streamlit Markdown generation/import, guided `.md` policy builder, queue,
  approve/reject/edit, guarded publish, history, score, token, cost, and retry views.
- Resumable 10-topic x 3-policy evaluation with raw-output comparisons.

The system includes guarded Facebook Page and Threads text publishing.
Authentication/RBAC, multi-tenancy, media uploads, a cloud database, and a full
web application remain outside this release.

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
in that file. Meta credentials are optional unless `--publish-mode live` is
used; see [Meta publishing](docs/meta_publishing.md).

In Streamlit, a key pasted under **AI connections** is a session-only manual
override. If the field is blank, the app falls back to the system default:
`.env` locally or Streamlit Secrets in Cloud. **Test connections** validates
the credential, endpoint, and selected model without generating a post.

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

Create from supplied content instead of topic alone:

```cmd
python run.py --account responsible-ai-lab ^
  --topic "Product release" ^
  --instructions "Adapt this into a practical Threads launch post" ^
  --content-file release-notes.md ^
  --content-task repurpose
```

`--content-file` accepts UTF-8 `.md` or `.txt`. It is source material for one
run, not an account policy. Use `--content` for short inline source text.
`repurpose`, `rewrite`, and `summarize` require source content; `create` can
work from the topic alone or use source content as reference.

Every configured account:

```cmd
python run.py --all --topic "Responsible AI for small teams"
```

Only policies with `active: true` participate in `--all`. Set `active: false`
to pause an account without deleting its policy or audit history.

Day 1 draft-only compatibility:

```cmd
python run.py --account responsible-ai-lab --pipeline draft --topic "Responsible AI for small teams"
```

The default database is `artifacts/content_agent.sqlite3`. Full runs either
mock/dry-run a safe post or leave it in `human_review`; rejected, failed, and
unapproved content cannot publish. Exit code `4` means the batch stopped before
the next account because a provider/application quota was exhausted.

## Guarded Meta publishing

New policies default to the mock adapter. A real policy contains only a public
target ID and uppercase `credential_ref`; the referenced token stays in `.env`
or a secret manager. The IDs in the bundled example policies are placeholders;
replace them with IDs you own. Approve the run in Streamlit, then validate
delivery:

```cmd
python run.py --publish-approved RUN_ID --publish-mode dry-run
```

After checking the stored receipt, live delivery requires an explicit gate:

```cmd
python run.py --publish-approved RUN_ID --publish-mode live
```

Facebook uses a Page access token; password-based personal-profile automation
is not supported. That includes clone-account password/cookie/session
automation: use an operator-authorized Facebook Page instead. Threads uses the
container + publish flow. Tokens are never put in URLs, logs, SQLite payloads,
or Markdown.

The exact manual token slot is the policy's `credential_ref`. For the bundled
Threads account it is:

```dotenv
# .env
THREADS_RESPONSIBLE_AI_TOKEN=paste_or_replace_your_threads_token_here
```

Check configuration without revealing the value:

```cmd
python run.py --list-accounts
```

The line reports `credential_ref`, `credential_present=true|false`, and
`topic_tag_mode`. When a token expires, replace the value after `=` in `.env`
and rerun the command; do not edit a token into `accounts/*.md`.

Threads policy example:

```md
## Publishing
- adapter: threads
- target_id: YOUR_THREADS_USER_ID
- credential_ref: THREADS_RESPONSIBLE_AI_TOKEN
- topic_tag: Responsible AI
- topic_tag_candidates: Responsible AI | AI Tools | AI for Business
- trend_search: true
- approval_required: true
```

With `trend_search: true`, the publisher searches only those configured,
niche-relevant candidates over recent Threads results and uses the candidate
with the most matches. It does not inject an unrelated global trend.

## Run the guided Content Studio

Start Streamlit against the same SQLite file used by the CLI:

```cmd
streamlit run streamlit_app.py
```

Open `http://localhost:8501`. The six numbered tabs guide the complete flow:

1. connect provider keys in `.env` or session-only password fields;
2. choose a channel and upload one UTF-8 content `.md`;
3. use `mode: generate` for AI creation or `mode: publish` for a finished post;
4. inspect/edit/approve the scored post;
5. run guarded dry-run and optional live delivery;
6. inspect all evidence, tokens, retries, and help.

It provides:

- strict one-file Markdown parsing with downloadable generate/publish templates;
- content-request-to-post Research, Copywriter, Critic, and bounded rewrite execution;
- four content tasks: create, repurpose, rewrite, and summarize;
- frozen source-content lineage visible during generation, review, and publish;
- a guided channel/profile form that generates the policy behind the scenes;
- an advanced Markdown editor, validation, import, and download for admins;
- current run and human-review queues;
- approve-to-queue, reject, and immutable edit actions with operator audit;
- a persistent latest-action result showing success/failure, new state, Run ID,
  Draft ID, operator, and guarded publish commands after approval;
- optional dry-run plus one-click live publish with backend state, permission,
  credential, placeholder-ID, and idempotency guards;
- Threads OAuth code exchange, encrypted long-lived token persistence, and
  automatic rotation before expiry;
- run events, artifacts, revisions, and delivery decisions;
- score history plus token/cost/request/retry metrics per run and provider;
- one canonical SQLite operations store;
- unique snapshot download names with timestamp/random suffix and at most 20
  retained local snapshots.

The Streamlit and CLI paths do not duplicate orchestration logic: both call the
same `PipelineOrchestrator`.

See the [Vietnamese end-to-end user journey](docs/user_journey_vi.md) for the
content templates, Facebook setup, one-click publish flow, and step-by-step
Threads OAuth instructions.

## Scheduled GitHub Actions batch

`.github/workflows/batch.yml` supports manual dispatch and runs at 08:17 and
20:17 in `Asia/Ho_Chi_Minh`. Add the three provider credentials as repository
Actions Secrets. For Meta delivery, add the matching
`FACEBOOK_COMMUNITY_PAGE_TOKEN` and/or `THREADS_RESPONSIBLE_AI_TOKEN` Secret.
Scheduled workflows only run after this workflow is on the repository default
branch.

Scheduled publishing is fail-safe by default:

- repository variable `CONTENT_AGENT_PUBLISH_MODE` is absent or `dry-run`;
- each real bundled policy has `approval_required: true`;
- target IDs are placeholders.

Only after a successful dry-run, replace the target ID, set the repository
variable to `live`, and set `approval_required: false` for an account that may
publish unattended. Keep `approval_required: true` if every post must be
reviewed; publish its approved run explicitly from the CLI instead.

The workflow restores the most recent non-expired `content-agent-latest`
artifact when possible, runs all accounts, and uploads the resulting SQLite
snapshot. Artifacts are a bounded evidence handoff, not a durable database.

## Streamlit Community Cloud

Deploy the root file `streamlit_app.py` with Python 3.11. Add provider keys in
Streamlit Secrets for persistent Cloud generation, or paste session-only keys
in the sidebar. Because Community Cloud local files are semi-persistent and its
machine is separate from GitHub Actions:

1. download `content-agent-latest` from the latest Actions run;
2. expand the artifact and upload `content_agent.sqlite3` under
   **Analytics → Data transfer**;
3. perform human review;
4. download the reviewed uniquely named SQLite snapshot before a reboot or redeploy.

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

Edit only the Markdown policy; Git supplies its version history. Account
activation, provider/model routes, review gating, and publisher destination all
come from that file. Use `active: false` to pause an account safely; removing
its Markdown file removes it from future `--all` discovery while historical
SQLite runs remain intact.

## Project map

```text
.github/workflows/          offline CI and twice-daily batch automation
accounts/                   Markdown policies and account template
evaluation/                 fixed ten-topic evaluation set
run.py                      CLI/scheduled content-generation entrypoint
streamlit_app.py            guided create/review/publish studio
scripts/evaluate.py         resumable 30-case evaluation
src/content_agent/          orchestrator, agents, quota, review, publisher
src/content_agent/platform/ SQLite schema, event log, usage, audit queries
tests/                      offline contracts, integration, UI, safety tests
```

## Safety boundary

- Social APIs are unreachable unless the operator passes `--publish-mode live`.
- Markdown contains secret references, never tokens or passwords.
- Facebook Page and Threads requests use bearer authorization and deterministic
  delivery reservations.
- Hard policy violations cannot be waived by the LLM or a reviewer.
- Copywriter/rewriter and Critic use different providers.
- Provider retries do not consume the two-rewrite content budget.
- Every failure has a normalized code and persisted event trail.
- Provider keys stay in local environment variables or Actions Secrets.

Read [architecture](docs/architecture.md),
[Meta publishing](docs/meta_publishing.md),
[known limitations](docs/known_limitations.md), and
[release evidence](docs/day2_day3_evidence.md).
