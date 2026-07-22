# Known limitations

- Publishing is mocked; no X, Facebook, Threads, or LinkedIn API is called.
- Research uses supplied context and model knowledge, not live web grounding.
- Free-tier provider quotas/catalogs can change and provide no SLA.
- Estimated dollar cost remains unknown when a free-tier route provides only
  token counts.
- Streamlit Community Cloud uses snapshot handoff; it is not a shared durable
  database between scheduled Actions and reviewers.
- The MVP has no authentication, RBAC, multi-tenancy, API server, or cloud DB.
- Human edits remain in review until explicitly approved; the dashboard does
  not silently spend quota by rerunning the LLM Critic.
- Deterministic banned-term checks use normalized literal phrase matching;
  semantic variants are left to the LLM Critic and human reviewer.
- GitHub scheduled runs can be delayed and execute only from the default branch.
- The 30-case live evaluation consumes substantial free-tier quota and must be
  run/resumed deliberately rather than from CI.
