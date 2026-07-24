# AI-01 free-tier provider matrix

Checked on 21 July 2026. These routes are for a controlled MVP and demo, not a
production SLA. Free quotas and catalogs can change without notice.

| Role | Provider | Primary model | Fallback | Structured-output strategy | Free-tier status |
|---|---|---|---|---|---|
| Research | Gemini Developer API | `gemini-3.1-flash-lite` | `gemini-3.5-flash` | Gemini JSON schema + local Pydantic validation | Input/output free on the free tier; grounding is disabled in this implementation |
| Copywriter | Groq Free Plan | `openai/gpt-oss-120b` | `qwen/qwen3.6-27b` | JSON object mode + local Pydantic validation | Production model; quota is controlled by the organization Limits page |
| LLM Critic spike | GitHub Models | `openai/gpt-4o-mini` | `openai/gpt-4.1-mini` | JSON object mode + local Pydantic validation | Included free, rate-limited prototyping usage |

Lifecycle update: Groq announced that `llama-3.3-70b-versatile` shuts down for
free/developer tiers on 16 August 2026. The runtime default was migrated to
Groq's recommended production model `openai/gpt-oss-120b`; the original model
name is retained only in historical live-evidence rows below.

Cost controls in this implementation:

- no paid/flex service tier is requested;
- no Gemini Search grounding is enabled;
- default tests use fake providers and consume zero API quota;
- the live spike uses one request per primary provider;
- fallback calls happen only with the explicit `--include-fallbacks` flag;
- provider responses do not reliably expose account billing state, so cost is
  stored as `null` instead of claiming a false dollar value.

Privacy note: Google's free tier may use submitted content to improve Google
products. Use only synthetic/non-confidential sprint data in this MVP.

Official references:

- [Gemini 3.1 Flash-Lite model](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite)
- [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing)
- [Gemini structured outputs](https://ai.google.dev/gemini-api/docs/structured-output)
- [Groq Free Plan rate limits](https://console.groq.com/docs/rate-limits)
- [Groq model deprecations](https://console.groq.com/docs/deprecations)
- [GitHub Models free prototyping and limits](https://docs.github.com/en/github-models/use-github-models/prototyping-with-ai-models)
- [GitHub Models inference API](https://docs.github.com/en/rest/models/inference)

## Credential evidence

The live command writes `artifacts/provider_spike_results.json`. The artifact
contains provider/model/prompt/usage metadata and validated sample objects, but
never credential values. Do not commit the artifact unless the team explicitly
decides to version acceptance evidence.

## Live validation result

The pre-migration primary routes were validated at `2026-07-21T08:30:42Z`
using one request per provider. Credential values were neither printed nor
written to evidence. A new live smoke run is required for the GPT-OSS route.

| Role | Provider/model | Result | Input | Output | Total | Latency |
|---|---|---:|---:|---:|---:|---:|
| Research | `gemini/gemini-3.1-flash-lite` | PASS | 350 | 349 | 699 | 2,326 ms |
| Copywriter | `groq/llama-3.3-70b-versatile` | PASS | 854 | 84 | 938 | 738 ms |
| Critic probe | `github_models/openai/gpt-4o-mini` | PASS | 828 | 37 | 865 | 3,554 ms |

All three responses passed local Pydantic validation. The integrated live
Gemini Research to Groq Copywriter run also passed: its draft referenced the
same `brief_id`, contained `#ResponsibleAI`, stayed at 176 content characters,
and contained neither configured banned term. The raw artifacts passed the
provider-secret pattern scan.
