# Day 2–3 acceptance evidence

| Requirement | Implementation | Offline evidence |
|---|---|---|
| Rule + LLM Critic | `critics.py`, `CriticAgent` | stable-code and hybrid decision tests |
| Provider separation | Groq Copywriter, GitHub Models Critic | registry/policy/full-pipeline tests |
| Maximum two rewrites | `FullPipelineOrchestrator.MAX_REWRITES` | fail-after-two E2E test |
| Human terminal queue | `workflow_items`, `ReviewService` | queue and provider-failure tests |
| Approve/reject/edit audit | Streamlit + `review_actions` | edit/approve and Publisher tests |
| Publisher safety | persisted-state `MockPublisher` guard | blocked human-review test |
| Retry/quota | bounded exponential provider wrapper | simulated 429/backoff test |
| Real dashboard data | SQLite query/service layer | Streamlit AppTest |
| `--all` | CLI account enumeration | CLI contract + three policy tests |
| Twice-daily/manual automation | `.github/workflows/batch.yml` | workflow source review |
| 30-output evaluation | ten frozen topics × three policies | topic/resume tests |
| Secrets | ignored local files and safe errors | repository security scan |

Live G2/G3 evidence is produced by the credentialed commands in README and must
record actual run IDs, the final SQLite snapshot, evaluation report, workflow
run URL, and deployed Streamlit URL against the same release commit.
