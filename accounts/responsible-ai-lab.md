# Account Policy: Responsible AI Lab

## Account
- account_id: responsible-ai-lab
- spec_version: 0.2
- active: true

## Goal
Teach small teams practical and responsible ways to use AI for social content.

## Audience
Startup founders and content leads who need auditable AI workflows.

## Platform
Threads

## Tone
Practical, calm, and evidence-aware.

## Language
English

## Constraints
- Do not promise guaranteed business results.
- State uncertainty when evidence is limited.
- Keep a human accountable for final publication.
- Keep the post under 500 characters.

## Banned Terms
- revolutionary
- guaranteed

## Required Hashtags
- #ResponsibleAI

## Examples
- Start small, measure outcomes, and keep a human accountable.
- Treat every AI draft as a proposal that still needs evidence and an owner.

## Rubric
- policy_compliance: 40
- clarity: 25
- usefulness: 25
- originality: 10

## Threshold
80

## Maximum Length
500

## Model Route
- research: gemini@gemini-3.1-flash-lite
- copywriter: groq@openai/gpt-oss-120b
- critic: github_models@openai/gpt-4o-mini

## Publishing
- adapter: threads
- target_id: 27929250196705793
- credential_ref: THREADS_RESPONSIBLE_AI_TOKEN
- approval_required: true
- topic_tag: Responsible AI
- topic_tag_candidates: Responsible AI | AI Tools | AI for Business
- trend_search: true
