# Day 2-3 release evidence matrix

This file separates offline code evidence from live-provider acceptance
evidence. A working code path is not called a completed live run until its run
ID exists in the retained SQLite snapshot.

## Sprint tasks

| Requirement | Status | Evidence |
|---|---|---|
| AI-02 hybrid Critic and rewrite | Code-verified | pass/rewrite/fail integration tests; full revision chain |
| PLT-02 state/retry/review/Publisher | Code-verified | two-rewrite cap, 429 retry, quota stop, Facebook/Threads guarded Publisher tests |
| UI-01 guided Streamlit studio | Code-verified | AppTest covers topic/brief/source inputs, policy studio, real queue, validation failure, and approval |
| PLT-03 `--all` and automation | Code-verified | three-policy CLI plus manual/twice-daily workflow |
| AI-03 30-output evaluation | Code complete; live pending | frozen topics, checkpoint/resume, raw comparison/usage/version report tests |
| QA-01 acceptance/demo | Code/docs ready; recording pending | README, deployment guide, demo script, matrix below |

## AC1-AC6

| ID | Acceptance criterion | Offline evidence | Live evidence still required |
|---|---|---|---|
| AC1 | Add account 4 without Python change | Markdown template/parser and discovery tests | Commit only a new `.md`, retain its run ID |
| AC2 | Constraint change alters output | Policy-driven prompts and deterministic rules | Retain before/after run IDs |
| AC3 | Copywriter and Critic use different providers | registry, policy, orchestration separation tests | Provider metadata from live SQLite |
| AC4 | Rate limit handled gracefully | simulated 429/backoff plus quota auto-stop | Optional provider-side 429 evidence |
| AC5 | No API key in repository | shareable-file secret scan | Repository secret-scan/check URL |
| AC6 | Failed content never auto-publishes | fail-after-two, reject, hard-rule approval guard, Publisher tests | Human-review run and audit action |

## Verified on 2026-07-22

- `.venv\Scripts\python.exe -m unittest discover -s tests -v`: 67 tests pass.
- `.venv\Scripts\python.exe -m compileall -q run.py streamlit_app.py src scripts tests`: pass.
- `.venv\Scripts\python.exe -m pip check`: no broken requirements.
- `run.py --list-accounts`: three valid account policies.
- Streamlit AppTest: empty database and real review queue render successfully.
- Streamlit server health endpoint: HTTP 200 `ok`.
- SQLite WAL and consistent online-backup tests: pass.
- Deployment URL supplied by operator: `https://content-agent-ops.streamlit.app`.

## Verified on 2026-07-24

- `.venv\Scripts\python.exe -m pytest -q`: 112 tests pass,
  including the guided policy-to-source-content-to-approval-to-Threads-dry-run
  journey.
- Ruff check and format check: pass.
- Compileall and `pip check`: pass; no broken requirements.
- `git diff --check`: pass; only Windows line-ending notices were emitted.
- Isolated package build: `content_agent_system-0.7.0` wheel and source
  distribution built successfully.
- Live provider smoke: Gemini Research, Groq Copywriter, and GitHub Models
  Critic all pass with the policy-selected models.
- Safe model-list probes return HTTP 200/ready for Gemini, Groq, and GitHub
  Models using the system defaults. They make no content-generation request.
- Network incident `d0cf636e-1905-46e0-8b68-735fe587096a` retained three
  Gemini retries and a safe `network` terminal error; the replacement UI now
  distinguishes configured credentials from reachable provider endpoints.
- Snapshot tests prove 50 generated names are unique and a 25-snapshot sequence
  retains exactly the newest 20 without replacing the canonical operations DB.
- Live one-case end-to-end smoke: 1 completed, 0 failed, Critic score 85,
  workflow routed to `human_review`, three provider requests, zero retries.
- Live guided-UI smoke: a separate topic, operator brief, and pasted source
  content flowed through Streamlit generation, human approval, a fresh
  dashboard session, and Threads dry-run for run
  `3a0366d8-5117-4fe6-b8a0-db7d58ce2689`; the same request ID is retained by
  Research and Draft, Critic score 85, 4,316 total tokens, three provider
  requests, zero retries, and zero external Meta requests.
- Approval-to-CLI Facebook dry-run: pass; repeating the command returns the
  same publish receipt and performs no external Meta request.
- Real Facebook/Threads HTTP paths, authorization headers, retry behavior,
  missing-secret handling, migration, and idempotency are verified with mocked
  HTTP clients. No real social post was created.

## Required before declaring the live release complete

1. Review, commit, and push this implementation branch; verify Community Cloud
   redeploys the guided studio.
2. Replace the placeholder Meta target IDs, configure operator-owned tokens,
   and perform a controlled live post to dedicated test accounts.
3. Run/resume all 30 evaluation cases and retain JSON plus SQLite evidence.
4. Merge the scheduled workflow to the default branch, configure Actions
   Secrets, and retain one successful workflow URL/artifact.
5. Load that artifact into Streamlit, complete one human-review action, download
   the reviewed database, then record the five-minute demo.

Day 1 live evidence remains in
`docs/evidence/day1_g1_live_2026-07-22.md`.

## Reverified on 2026-07-25

- 112/112 automated tests pass; Ruff check/format, compileall, `pip check`, and
  `git diff --check` pass.
- Safe connection probes return HTTP 200/ready for Gemini Research, Groq
  Copywriter, and GitHub Models Critic using system-default credentials.
- Fresh prompt-first Quick Composer live smoke passed for run
  `d2f15f7c-23b5-4003-a492-1f4ed0ceb76f`: a normal user supplied only a
  channel, topic, and desired-post prompt (no Markdown/source file); the
  Request ID remained linked through Research and Draft, Critic score 85,
  human approval was audited, publishing ended in `dry_run`, 4,187 total
  tokens, three provider requests, zero retries, and zero external Meta
  requests.
  Retained report: `artifacts/ui_live_smoke_report.json`.
- Recording-ready Vietnamese instructions:
  `docs/demo_guide_vi.md`.
