# Account Policy: Replace With Display Name

## Account
- account_id: replace-with-slug
- spec_version: 0.2
- active: true

## Goal
Describe the measurable communication goal for this account.

## Audience
Describe the people this account serves.

## Platform
LinkedIn

## Tone
Describe the voice using specific adjectives.

## Language
English

## Constraints
- Add at least one explicit content constraint.

## Banned Terms
- add-a-banned-term

## Required Hashtags
- #AddAHashtag

## Examples
- Add one short example that demonstrates the desired style.
- Add a second example so the model can distinguish the account voice.

## Rubric
- policy_compliance: 40
- clarity: 30
- usefulness: 20
- originality: 10

## Threshold
80

## Maximum Length
900

## Model Route
- research: gemini@gemini-3.1-flash-lite
- copywriter: groq@openai/gpt-oss-120b
- critic: groq@openai/gpt-oss-20b

## Publishing
- adapter: mock
- approval_required: true

<!-- Threads may also set topic_tag, pipe-separated topic_tag_candidates, and trend_search. -->
