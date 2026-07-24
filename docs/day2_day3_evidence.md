# Day 2-3 release evidence matrix

This file separates offline code evidence from live-provider acceptance
evidence. A working code path is not called a completed live run until its run
ID exists in the retained SQLite snapshot.

## Sprint tasks

| Requirement | Status | Evidence |
|---|---|---|
| AI-02 hybrid Critic and rewrite | Code-verified | pass/rewrite/fail integration tests; full revision chain |
| PLT-02 state/retry/review/Publisher | Code-verified | two-rewrite cap, 429 retry, quota stop, guarded Publisher tests |
| UI-01 Streamlit review surface | Code-verified | AppTest against empty and real SQLite queue; no generation import |
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

## Required before declaring the live release complete

1. Review, commit, and push this implementation branch; verify Community Cloud
   redeploys the review-only dashboard.
2. Run one full account through the CLI and retain run ID, provider metadata,
   final state, SQLite snapshot, and screenshot.
3. Run/resume all 30 evaluation cases and retain JSON plus SQLite evidence.
4. Merge the scheduled workflow to the default branch, configure Actions
   Secrets, and retain one successful workflow URL/artifact.
5. Load that artifact into Streamlit, complete one human-review action, download
   the reviewed database, then record the five-minute demo.

Day 1 live evidence remains in
`docs/evidence/day1_g1_live_2026-07-22.md`.
