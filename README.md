# Social Content Agent System — Day 1 MVP

This repository implements the complete Monday/G1 vertical slice from the
Wednesday MVP sprint plan:

```text
Markdown AccountPolicy -> Gemini Research -> Groq Copywriter -> SQLite
```

One CLI invocation loads a validated account policy, creates one `run_id`,
executes both structured AI agents, and persists the `AccountPolicy`,
`ResearchBrief`, `DraftPost`, and ordered `RunEvent` records in one database.

## Day 1 scope

- **AI-01 (Trọng):** strict AI schemas, Gemini/Groq/GitHub Models adapters,
  provider routing, versioned prompts, normalized provider errors, and live
  provider-spike tooling.
- **PLT-01 (Tín):** repository skeleton, CLI, frozen run/event contracts,
  orchestrator, SQLite schema, traceable failures, dependency entry point, and
  minimal CI.
- **POL-01 (Tài):** Policy Spec v0.1, Markdown parser with actionable errors,
  template, three differentiated account policies, and valid/invalid fixtures.

Day 2 critic/rewrite/human-review/Publisher work and Day 3 evaluation/release
work are intentionally outside this branch's Day 1 boundary.

## Architecture

```text
accounts/<slug>.md
        |
        v
  AccountPolicy parser/validation
        |
        v
  Day1Orchestrator ---------> SQLite runs + policies + artifacts + run_events
        |                                      ^
        +--> Gemini ResearchBrief -------------+
        |                                      |
        +--> Groq DraftPost --------------------+
```

The provider adapters never receive credentials in prompts. Shareable files
contain blank environment-variable values only, and normalized provider errors
exclude request headers and API keys.

## Quick start (Windows, under 10 minutes)

From the repository root:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Fill in `.env` locally:

```dotenv
GEMINI_API_KEY=<your-own-gemini-key>
GEMINI_MODEL=gemini-3.1-flash-lite

GROQ_API_KEY=<your-own-groq-key>
GROQ_MODEL=llama-3.3-70b-versatile

GITHUB_MODELS_TOKEN=<your-own-github-models-token>
GITHUB_MODELS_MODEL=openai/gpt-4o-mini
```

Never commit `.env`, paste keys into prompts, or include them in screenshots,
logs, issues, pull requests, or artifacts.

## Verify without spending provider quota

```powershell
python run.py --help
python run.py --list-accounts
python scripts/provider_spike.py --dry-run
python -m unittest discover -s tests -v
```

Expected account list:

```text
community-learning      Facebook    max_length=1200
responsible-ai-lab      LinkedIn    max_length=900
startup-growth          X           max_length=280
```

The offline suite covers policy validation, AI handoffs, provider separation,
structured responses, error normalization, SQLite persistence, one-run
traceability, CLI behavior, rate-limit failure state, and secret scanning.

## Run the integrated Day 1 vertical slice

This uses one Gemini request and one Groq request:

```powershell
python run.py --account responsible-ai-lab `
  --topic "How small teams can use AI responsibly for social content"
```

An account slug resolves to `accounts/<slug>.md`. An explicit policy path also
works:

```powershell
python run.py --account accounts/startup-growth.md `
  --topic "A practical weekly growth experiment"
```

Success output contains the shared `run_id`, linked research/draft IDs, and the
database path. The default database is `artifacts/day1.sqlite3` and is ignored
by Git. Missing policies exit with code 2; safe provider/pipeline failures exit
with code 3 and persist the failed state under the printed `run_id`.

## Inspect a run in SQLite

The G1 evidence is stored in four tables:

- `runs`: account, topic, terminal state, and safe failure fields;
- `policies`: source file, Policy Spec version, and parsed policy JSON;
- `artifacts`: `account_policy`, `research_brief`, and `draft_post` JSON;
- `run_events`: ordered step/state/attempt, provider/model, token/cost, and
  normalized error metadata.

Use any SQLite viewer, or run this read-only Python command after replacing the
ID:

```powershell
python -c "import sqlite3; db=sqlite3.connect('artifacts/day1.sqlite3'); db.row_factory=sqlite3.Row; print(dict(db.execute('select * from runs where run_id=?', ('<run_id>',)).fetchone()))"
```

The consumer invariant is
`DraftPost.brief_id == ResearchBrief.brief_id`, and all policy, artifact, and
event rows reference that same `run_id`.

## Add account 4 without changing Python

```powershell
Copy-Item accounts/template.md accounts/account-4.md
```

Edit only the new Markdown file, then validate it:

```powershell
python run.py --list-accounts
python run.py --account account-4 --topic "Your topic"
```

The exact syntax, required sections, and validation rules are in
[`docs/policy_spec.md`](docs/policy_spec.md).

## Provider validation

| Role | Provider | Primary model | Credential |
|---|---|---|---|
| Research | Gemini | `gemini-3.1-flash-lite` | `GEMINI_API_KEY` |
| Copywriter | Groq | `llama-3.3-70b-versatile` | `GROQ_API_KEY` |
| Critic contract probe | GitHub Models | `openai/gpt-4o-mini` | `GITHUB_MODELS_TOKEN` |

Run one schema-valid request per primary provider:

```powershell
python scripts/provider_spike.py --provider all
```

Run the direct Gemini-to-Groq AI handoff without platform persistence:

```powershell
python scripts/ai_day1_demo.py
```

Provider artifacts are written under `artifacts/` and must never include a
credential. Free-tier quotas and model catalogs are not SLAs; use
`docs/ai/provider_matrix.md` for the pinned fallback decisions.

## Project layout

```text
.github/workflows/ci.yml       minimal push/PR/manual CI
accounts/                      template + three Markdown policies
docs/                          Policy, platform, AI, and G1 handoff docs
pyproject.toml                 installable package metadata and tool config
run.py                         integrated Day 1 CLI
scripts/                       live provider and AI handoff checks
src/content_agent/ai/          contracts, prompts, agents, providers, routing
src/content_agent/platform/    RunEvent contract and SQLite store
src/content_agent/policy.py    AccountPolicy and Markdown parser
src/content_agent/orchestrator.py
tests/                         offline contract/unit/integration/security tests
```

## Day 1 Definition of Done

- Three differentiated policies and the template parse through one strict
  Markdown contract; invalid input names the file and section.
- Research and Copywriter consume the parsed `AccountPolicy` and return strict,
  linked schemas with provider/model/prompt/usage metadata.
- A single CLI run persists policy, research, draft, and events under one
  `run_id`; the success and provider-failure paths are tested.
- `python run.py --help`, account validation, the test suite, and minimal CI
  pass without credentials.
- `.env` and runtime databases/artifacts are ignored; the security test finds
  no provider credential in shareable files.

See `docs/day1_g1_evidence.md` for the cross-owner evidence matrix and
`docs/platform/day1_contracts.md` for the frozen database/event contract.
