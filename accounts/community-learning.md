# Account Policy: Community Learning

## Account
- account_id: community-learning
- spec_version: 0.2
- active: true

## Goal
Make trustworthy AI concepts accessible to community educators and adult learners.

## Audience
Community educators, nonprofit teams, and curious adult learners.

## Platform
Facebook

## Tone
Warm, inclusive, patient, and free of unnecessary jargon.

## Language
English

## Constraints
- Explain technical terms in plain language.
- Include one reflective question for discussion.
- Avoid fear-based framing and unsupported claims.
- Keep the post under 1200 characters.

## Banned Terms
- magic
- replaces humans

## Required Hashtags
- #AILiteracy

## Examples
- AI is a tool that predicts patterns; people still choose the goals and check the result.
- Before sharing an AI answer, ask what evidence supports it and what might be missing.

## Rubric
- policy_compliance: 35
- clarity: 30
- usefulness: 20
- inclusiveness: 15

## Threshold
78

## Maximum Length
1200

## Model Route
- research: gemini@gemini-3.1-flash-lite
- copywriter: groq@openai/gpt-oss-120b
- critic: github_models@openai/gpt-4o-mini

## Publishing
- adapter: facebook_page
- target_id: 000000000000001
- credential_ref: FACEBOOK_COMMUNITY_PAGE_TOKEN
- approval_required: true
