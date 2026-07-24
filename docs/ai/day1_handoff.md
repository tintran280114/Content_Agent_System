# AI-01 Day 1 integrated handoff

Trọng's structured AI interfaces are consumed by `PipelineOrchestrator` in draft mode without an
adapter shim. Tài's canonical `AccountPolicy` is normalized by
`PolicyContext.from_policy()` for prompt construction, while Tín's platform
persists the complete policy object.

The integrated call order is:

```python
policy = load_policy(policy_path)
brief = ResearchAgent(create_role_provider(Role.RESEARCH)).run(
    topic=topic,
    policy=policy,
)
draft = CopywriterAgent(create_role_provider(Role.COPYWRITER)).run(
    research=brief,
    policy=policy,
)
```

`ResearchBrief` and `DraftPost` contain provider, model, role, prompt version,
SDK version, request ID when available, latency, and token usage. The platform
persists them as `research_brief` and `draft_post`; it asserts
`DraftPost.brief_id == ResearchBrief.brief_id`.

All provider failures become `ProviderError` with stable `code`, `message`,
`provider`, `model`, `retryable`, and `status_code` fields. The orchestrator
stores those fields in a failed `RunEvent` and never records provider exception
bodies or request headers.

Offline verification:

```powershell
python -m unittest discover -s tests -v
```

Live G1 verification (one Gemini and one Groq request):

```powershell
python run.py --account responsible-ai-lab --topic "Responsible AI for small teams"
```
