# AI-01 Day 1 definition-of-done evidence

| Requirement | Evidence |
|---|---|
| Validate Gemini, Groq, and GitHub Models routes | `scripts/provider_spike.py`; ignored live artifact |
| Strict ResearchBrief, DraftPost, CriticResult | AI models, fixtures, schema tests |
| Policy-conditioned Research and Copywriter | prompt assertions and integrated orchestrator test |
| Provider/model/prompt/usage metadata | `GenerationMetadata` and persisted completion events |
| Copywriter/Critic provider separation | route registry, AccountPolicy validator, tests |
| Actionable safe failures | normalized ProviderError and failed-run integration test |
| Complete shared G1 handoff | `run.py` + Markdown parser + SQLite on one `run_id` |

The AI unit scope and the cross-owner offline G1 integration gate are GREEN.
Live provider evidence remains an explicit credentialed command because runtime
artifacts and credentials are intentionally excluded from version control.
