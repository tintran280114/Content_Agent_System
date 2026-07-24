# Known limitations

- Publishing is mocked; no social-network API is called.
- Research uses supplied context and model knowledge, not live web grounding.
- Provider quotas/catalogs can change and free tiers have no SLA.
- Estimated dollar cost is `null` when a provider reports tokens but no price.
- Community Cloud local SQLite is semi-persistent and separate from Actions;
  snapshot handoff is manual and must be downloaded before a reboot.
- GitHub artifact retention is bounded, so it is evidence storage rather than a
  durable operational database.
- The MVP has no authentication, RBAC, multi-tenancy, API server, or cloud DB.
- Human edits remain in review until explicitly approved and rule-checked.
- Banned-term rules use normalized literal matching; semantic variants rely on
  the LLM Critic and reviewer.
- Scheduled GitHub workflows run only from the default branch and may be
  delayed during service load.
- The live 30-case evaluation consumes provider quota and is deliberately
  resumable rather than part of offline CI.
