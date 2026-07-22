# Wednesday MVP architecture

## Runtime split

The system has two surfaces:

1. `run.py` is the authoritative batch runtime. It is invoked locally, from
   cron, or from GitHub Actions and exits after a bounded run.
2. `streamlit_app.py` is the only interactive surface. It reads persisted state
   and calls `ReviewService`; it contains no provider orchestration or direct
   review-action SQL.

There is deliberately no API server or JavaScript frontend.

## Full pipeline

```text
AccountPolicy
  → ResearchBrief (Gemini)
  → DraftPost revision 0 (Groq)
  → RuleCriticResult (local)
  → CriticResult (GitHub Models)
      ├─ PASS → PASSED → MockPublisher → PUBLISHED
      ├─ REWRITE and count < 2 → Groq revision → Critic loop
      └─ failure/count=2 → HUMAN_REVIEW
             ├─ approve + note → APPROVED → MockPublisher
             ├─ edit → immutable HUMAN_EDIT revision → still requires approval
             └─ reject → REJECTED
```

The LLM result is advisory around hard constraints. Final `PASS` requires:

- deterministic rules pass;
- LLM score meets the account threshold; and
- the LLM returns `decision=pass`.

## SQLite 0.2

Day 1 tables remain intact. Day 2–3 add only new tables:

| Table | Purpose |
|---|---|
| `workflow_items` | Authoritative review/publish state, rewrite cap, optimistic version |
| `draft_revisions` | Initial AI, AI rewrite, and human edit payloads |
| `critic_results` | Rule and LLM evidence for each AI revision |
| `review_actions` | Operator/action/note/edit/time audit |
| `publish_attempts` | Accepted and blocked mock Publisher receipts |
| `evaluation_cases` | Incremental/resumable 10×3 progress |

`runs.state` describes batch execution (`running/completed/failed`), while
`workflow_items.state` describes content safety and operator state. This keeps
the Day 1 contract backward compatible.

## Failure behavior

- Retryable provider failures use at most three provider attempts with bounded
  exponential backoff.
- A failure before any draft exists fails the run safely.
- A failure after a valid draft exists routes that draft to human review with a
  normalized code/message.
- Provider retries do not increase the AI rewrite count.
- The Publisher reads the authoritative persisted workflow state instead of
  trusting caller input.
