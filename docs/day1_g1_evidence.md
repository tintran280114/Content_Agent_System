# Integrated Day 1 / G1 evidence matrix

| Sprint requirement | Repository evidence | Automated proof |
|---|---|---|
| Three differentiated Markdown policies | `accounts/*.md`, excluding template | `test_three_differentiated_account_policies_parse` |
| File/section-specific parser failures | `content_agent.policy.PolicyParseError` | invalid-section and rubric tests |
| Tài policy consumed by Trọng interfaces | `PipelineOrchestrator(mode=draft)` passes `AccountPolicy` to both agents | policy compatibility + orchestrator tests |
| Strict ResearchBrief/DraftPost contracts | `content_agent.ai.models` | schema fixtures and provider adapter tests |
| Frozen run states and SQLite schema | `platform/contracts.py`, `platform/storage.py` | success/failure integration tests |
| One shared run_id and linked artifacts | `PipelineOrchestrator.run(mode=draft)` | `test_vertical_slice_persists_every_contract_under_one_run_id` |
| Actionable safe provider failure | normalized `ProviderError` -> failed events/run | rate-limit integration + security tests |
| CLI and account discovery | `run.py` | help/list/missing-policy CLI tests |
| Minimal CI | `.github/workflows/ci.yml` | same offline commands as local verification |
| Installable repository bootstrap | `pyproject.toml`, `requirements.txt`, `.python-version` | package import/version test |
| No key in shareable files | blank examples + `.gitignore` | `test_security.py` |

## Gate status

- Automated G1 contract gate: **GREEN**.
- Live integrated G1 gate: **GREEN** — run
  `853676ed-e267-4d5b-b4a6-cad3d728f638` completed Policy → Gemini Research →
  Groq Copywriter → SQLite. See
  [`evidence/day1_g1_live_2026-07-22.md`](evidence/day1_g1_live_2026-07-22.md).
- The raw database remains in ignored `artifacts/day1.sqlite3`; the safe live
  evidence document is versionable and contains no credential.
- Remote host/access evidence must be verified on GitHub: both collaborators
  clone, create a short branch, and open a PR against `main`. Local source code
  cannot prove collaborator identity or approval state.

The test suite is the reproducible shared-commit proof. The recorded live run
confirms that `runs`, `policies`, `artifacts`, and `run_events` contain the same
identifier and terminal `completed` state.
