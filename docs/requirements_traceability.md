# Assignment requirements traceability

Source reviewed in full: `De_Bai_Social_Content_Agent_System.docx`.

This matrix separates code/test completion from live acceptance evidence. A
feature is not called live-complete merely because a mocked or deterministic
test passes.

## Full-document re-audit

| Word section | What it requires | Current result |
|---|---|---|
| 1. Context | many social accounts, policy-driven behavior, no hardcoded account behavior | implemented |
| 2.1 Orchestrator | scan policies, hand off topic, choose models, review, quota, logs | implemented |
| 2.2 Workers | Gemini Research, second-provider Copywriter, hybrid Critic, code Publisher | implemented |
| 2.3 Policy engine | one `.md` per account with goal, rules, examples, rubric | implemented |
| 2.4 Review loop | local rules, LLM score, no more than two rewrites, human queue | implemented |
| 3. Deliverables | repo/README, spec, three policies, dashboard, 30-case report, video | code/docs complete; live report and video pending |
| 4. Acceptance | account 4, constraint proof, provider split, rate limit, secrets, no failed auto-post | code-tested; retained live proof still listed below |
| 5. Technical constraints | Python, free tier, swappable/mock Publisher | implemented |
| 6. Team plan | ownership and week/checkpoint guidance | planning guidance, not a runtime feature |

The Word document defines Research as finding a topic/insight and does not
define an operator-supplied source-content field. The separate
`ContentRequest(topic, instructions, source_content)` contract is an explicit
product extension requested after the original assignment. It is implemented
without changing the account-policy contract.

## System requirements

| Assignment requirement | Status | Implementation/evidence |
|---|---|---|
| One orchestrator scans `accounts/*.md` | Complete | `PipelineOrchestrator`, CLI `--all`, policy discovery tests |
| Policy chooses topic handoff, model route, and review | Complete | `AccountPolicy` v0.2 and frozen per-run policy payload |
| Topic, operator brief, and source content remain distinct | Product extension complete | one content Markdown parser maps sections to frozen `ContentRequest`; lineage and agent-prompt tests |
| One content Markdown is sufficient | Product extension complete | `generate` and `publish` templates, CommonMark token parsing, direct-import audit, AppTest |
| Manual AI key override with system fallback | Product extension complete | session-only override, `.env`/Secrets fallback, source labels and UI tests |
| Diagnose configured-but-unreachable AI | Product extension complete | non-generation endpoint/model probes and safe network/auth/permission states |
| Collision-safe SQLite downloads | Product extension complete | one canonical DB plus randomized snapshot names and bounded 20-copy rotation |
| Quota, token/request tracking, retry/backoff, auto-stop | Complete | `QuotaManager`, run events, quota/retry tests |
| Full per-run model/token/retry/score/result logs | Complete | SQLite events, artifacts, critics, usage and dashboard Analytics |
| Research Agent on Gemini | Complete | Structured `ResearchBrief`, Gemini adapter and live provider smoke |
| Copywriter on a second provider | Complete | Groq structured `DraftPost` |
| Hybrid Critic on a different provider | Complete | local `RuleCritic` + GitHub Models `CriticResult` |
| Publisher is code-only and swappable | Complete | protocol + mock, Facebook Page, Threads adapters |
| One Markdown file per account | Complete | strict account-policy parser, three examples, template, guided builder/import |
| No typed `PUBLISH` confirmation | Complete | one-click UI; backend workflow, permission, credential, target and idempotency guards retained |
| Threads OAuth and silent refresh | Complete | OAuth code/long-lived exchange, encrypted store, expiry-aware proactive rotation |
| Goal, constraints, examples, rubric, threshold | Complete | required parser sections and Policy Studio form |
| Add/change account without Python edits | Complete in code/tests | UI builder saves validated `accounts/<slug>.md`; acceptance test creates a new policy |
| Hard rules cost zero tokens | Complete | deterministic rule step is logged without provider usage |
| At most two Copywriter rewrites | Complete | workflow cap and integration tests |
| Failure after two rewrites goes to human review | Complete | integration test and queue state |
| README setup under ten minutes | Complete | Windows setup and guided Studio flow |
| Policy specification | Complete | `docs/policy_spec.md` plus in-app Help |
| Three differentiated policies/platforms | Complete | Facebook, Threads, X/mock examples |
| Dashboard queue, score, cost/token | Complete | numbered Studio tabs and Analytics |
| Same ten topics × three policies evaluation | Code complete; live run pending | resumable 30-case runner/report tests; full retained live report still required |
| Demo video no more than five minutes | Pending external deliverable | `docs/demo_script.md` exists; video must still be recorded |

## Acceptance criteria

| Criterion | Current evidence | Remaining live proof |
|---|---|---|
| Add account 4 with only `.md` | strict builder/save/discovery tests | retain one live run ID for the new account |
| Change a hard constraint and output follows it | prompt injection + rule tests | retain before/after live run IDs |
| Copywriter and Critic use different providers | parser guard, registry test, provider metadata | already visible in live smoke metadata |
| Graceful free-tier rate limits | simulated 429, retry/backoff, quota stop | optional provider-side 429 capture |
| No key in code/repository | `.env`, session-only password fields, secret scan test | repository-host secret scan URL |
| Failed review content never auto-publishes | state guard, reject test, two-rewrite test | one recorded reviewer demonstration |

## Guided product flow added beyond the minimum dashboard requirement

The assignment only explicitly requires queue/score/cost in the dashboard.
The product now also provides:

1. provider-key readiness and session-only overrides;
2. one content Markdown upload that maps topic, writing brief and source;
3. `generate`/`publish` modes plus create, repurpose, rewrite, and summarize tasks;
4. a non-technical account-policy builder and `.md` importer;
5. generated-post preview/download with original-input lineage;
6. audited edit/approve/reject actions;
7. optional dry-run and one-click live publishing with backend guards;
8. Threads OAuth, encrypted token rotation and in-app setup guidance.

## Latest verification

- 126/126 automated tests pass after the Markdown/OAuth refactor.
- Ruff lint and formatting checks pass.
- Compileall and dependency consistency checks pass.
- Version 0.7.0 source distribution and wheel build successfully.
- A live guided-UI smoke used Gemini, Groq, and GitHub Models, then completed
  human approval and Threads dry-run without sending a request to Meta. See
  `artifacts/ui_live_smoke_report.json`.

## Honest release blockers

The implementation is not fully live-accepted until all of these are retained:

1. a completed 30-case evaluation report (10 topics × 3 policies);
2. one dedicated Facebook Page and/or Threads live post with operator-owned IDs
   and tokens;
3. a successful scheduled Actions run and downloaded SQLite artifact;
4. the required five-minute demo video;
5. commit/push/PR evidence for the final reviewed source state.
