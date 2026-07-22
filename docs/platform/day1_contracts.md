# PLT-01 frozen contracts

## Run state

A run starts as `running` and has exactly one terminal state: `completed` or
`failed`. Day 1 steps are `run`, `policy`, `research`, and `copywriter`.
Events use `started`, `completed`, or `failed`; `attempt` starts at 1.

`RunEvent` stores:

```text
run_id, step, state, attempt, provider, model,
input/output/total tokens, estimated cost,
error code/message, retryable, status code, created_at
```

Provider failures use the AI layer's normalized safe error taxonomy. Request
headers, exception bodies, and credentials are never persisted.

## SQLite schema v0.1

| Table | Purpose |
|---|---|
| `runs` | Shared run identity, account/topic, state, safe terminal error |
| `policies` | Source path, spec version, and parsed AccountPolicy JSON |
| `artifacts` | One policy, research brief, and draft JSON per run |
| `run_events` | Ordered state, provider/model, usage/cost, and error trace |
| `schema_meta` | Current SQLite contract version (`0.1`) |

Foreign keys bind every record to `runs.run_id`. `(run_id, kind)` is unique in
`artifacts`, making accidental duplicate Day 1 writes fail visibly. Each store
write uses an explicit SQLite transaction and enables foreign-key enforcement.

## Orchestration order

1. Parse and validate the Markdown before provider calls.
2. Create `run_id`; persist run, policy, and `run/policy` events.
3. Start Research, persist `ResearchBrief`, provider metadata, and usage.
4. Start Copywriter with that exact brief, persist linked `DraftPost` and usage.
5. Mark the run completed, or normalize the error and mark it failed.

The platform test asserts that the persisted draft's `brief_id` equals the
persisted research artifact ID and that Gemini/Groq completion events share the
same run.
