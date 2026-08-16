# Account Policy: LinkedIn Professional

## Account
- account_id: linkedin-professional
- spec_version: 0.2
- active: true

## Goal
Share practical professional insights that help software teams adopt responsible automation.

## Audience
Engineering leaders, product managers, and software practitioners.

## Platform
LinkedIn

## Tone
Clear, credible, practical, and conversational.

## Language
English

## Constraints
- Lead with a concrete lesson or observation.
- Do not make unsupported performance claims.
- Keep paragraphs short and readable.

## Banned Terms
- guaranteed

## Required Hashtags
- #ResponsibleAI

## Examples
- Reliable automation starts with a visible approval boundary and an auditable delivery record.
- A useful AI workflow makes retries safe, credentials private, and human ownership explicit.

## Rubric
- policy_compliance: 40
- clarity: 25
- usefulness: 25
- originality: 10

## Threshold
80

## Maximum Length
3000

## Model Route
- research: gemini@gemini-3.1-flash-lite
- copywriter: groq@openai/gpt-oss-120b
- critic: groq@openai/gpt-oss-20b

## Publishing
- adapter: linkedin
- target_id: urn:li:person:F_2cpdgULT
- credential_ref: LINKEDIN_EXAMPLE_ACCESS_TOKEN
- approval_required: true
