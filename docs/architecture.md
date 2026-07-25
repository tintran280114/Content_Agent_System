# Wednesday MVP architecture

## Runtime boundary

There are two user surfaces over one canonical application core:

1. `run.py` is the non-interactive entrypoint for local batches, cron, and
   GitHub Actions.
2. `streamlit_app.py` is the guided operator studio for creating content requests,
   building/importing account policies, running generation, reviewing,
   approving, dry-running, and explicitly publishing.

Both call the same `PipelineOrchestrator`, policy parser, `ReviewService`,
publisher router, quota manager, and SQLite contract. Streamlit is not a second
orchestrator. There is no API server, JavaScript frontend, or external database.

## One orchestrator

`PipelineOrchestrator` owns both modes:

- `draft`: Policy -> Research -> Copywriter, retained for Day 1 evidence;
- `full`: the same prefix followed by Critic, rewrite, review, and Publisher.

This prevents a second implementation from drifting away from the scheduled
production path.

```text
ContentRequest + AccountPolicy
  -> ResearchBrief (Gemini)
  -> DraftPost revision 0 (Groq)
  -> RuleCriticResult (local)
  -> CriticResult (GitHub Models)
          | PASS -> PASSED -> policy Publisher -> PUBLISHED / DRY_RUN
          | PASS + approval_required -> HUMAN_REVIEW -> APPROVED -> guarded UI/CLI Publisher
      | REWRITE and count < 2 -> Groq revision -> Critic loop
      | provider failure after draft / count = 2 -> HUMAN_REVIEW
          | approve + note -> guarded UI/CLI -> policy-selected Publisher
          | edit -> immutable HUMAN_EDIT revision -> still needs approval
          | reject -> REJECTED
```

Final `PASS` requires deterministic rules to pass, the score to meet the
account threshold, and the LLM decision to be `pass`.

## Reliability and quota boundary

- Retryable provider errors use at most three attempts and bounded exponential
  backoff.
- `QuotaManager` checks persisted daily request/token usage before each call
  and stops with `quota_exhausted` before an application budget is exceeded.
- Provider retries do not increment the content rewrite count.
- Failure before a valid draft fails the run; failure after a valid draft
  preserves it in human review.
- `Publisher` is a protocol. `PolicyPublisherRouter` reads the frozen policy and
  authoritative workflow state from SQLite. Meta adapters reserve an
  idempotency key before network I/O and require an explicit live-mode gate.

## SQLite ownership

SQLite uses foreign keys, WAL journal mode, a 30-second busy timeout,
transactions, and consistent online backups. Key tables are:

| Table | Purpose |
|---|---|
| `runs`, `run_events` | Batch state, provider/model usage, retry/error trail |
| `policies`, `artifacts` | Frozen policy, content request, and structured agent handoffs |
| `workflow_items` | Current safety/review state and two-rewrite cap |
| `draft_revisions` | Initial AI, AI rewrite, and human-edit payloads |
| `critic_results` | Rule and LLM score/decision evidence per revision |
| `review_actions` | Operator/action/note/edit/time audit |
| `publish_attempts` | Reserved, dry-run, failed, blocked, and published receipts |
| `evaluation_cases` | Incremental/resumable 10 x 3 progress |

`runs.state` describes execution (`running/completed/failed`), while
`workflow_items.state` describes content safety (`published/human_review/...`).

The runtime owns one canonical operations database. Snapshot downloads are
immutable copies with collision-resistant timestamp/random filenames. A bounded
rotation keeps at most 20 local copies; it does not create 20 independent
operational databases or split run history.

## Deployment topology

Local cron can use one persistent SQLite file directly. GitHub-hosted runners
and Streamlit Community Cloud are separate, ephemeral machines, so the Actions
artifact is downloaded and loaded into the dashboard as an explicit snapshot.
There is no claim of live cross-service database synchronization.
