# Known limitations

- Facebook Page and Threads adapters currently support text posts only; media,
  replies, scheduling, and analytics are not implemented.
- Live Meta acceptance still depends on operator-owned apps, App Review,
  permissions, valid target IDs, and access tokens.
- Threads trend-aware tagging compares recent result counts only among up to
  five operator-approved candidates. It is not a global trending-topic feed,
  and it requires the `threads_keyword_search` permission.
- Meta token acquisition and refresh remain manual. The CLI reports only
  present/missing status; it does not store passwords, cookies, app secrets, or
  refresh tokens.
- Research uses supplied context and model knowledge, not live web grounding.
- Source-content ingestion accepts UTF-8 `.md`/`.txt` or pasted text up to
  30,000 characters. PDF, Word, image OCR, URL fetching, and media generation
  are not included in this release.
- Provider quotas/catalogs can change and free tiers have no SLA.
- A configured key does not guarantee outbound connectivity. The in-app probe
  distinguishes missing/auth/permission/rate-limit/model/network states, but
  host firewall and proxy repair remains an operator responsibility.
- Estimated dollar cost is `null` when a provider reports tokens but no price.
- Community Cloud local SQLite is semi-persistent and separate from Actions;
  snapshot handoff is manual and must be downloaded before a reboot.
- GitHub artifact retention is bounded, so it is evidence storage rather than a
  durable operational database.
- The MVP has no authentication, RBAC, multi-tenancy, API server, or cloud DB.
- A publish reservation left `pending` after a process crash requires manual
  investigation; the system blocks automatic retry to avoid duplicate posts.
- Human edits remain in review until explicitly approved and rule-checked.
- Banned-term rules use normalized literal matching; semantic variants rely on
  the LLM Critic and reviewer.
- Scheduled GitHub workflows run only from the default branch and may be
  delayed during service load.
- The live 30-case evaluation consumes provider quota and is deliberately
  resumable rather than part of offline CI.
