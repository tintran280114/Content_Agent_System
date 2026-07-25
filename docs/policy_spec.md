# Account Policy Spec v0.2

An account is introduced through one UTF-8 Markdown file under `accounts/`.
No account-specific Python branch is allowed. Version `0.1` files remain
readable and default to an active account with the mock publisher.

## Required sections

Every file must contain these level-two headings exactly once:

1. `## Account`
   - `account_id`: unique lowercase slug.
   - `spec_version`: `0.2` for new policies.
   - `active`: `true` or `false`. `--all` skips inactive accounts.
2. `## Goal`, `## Audience`, `## Platform`, `## Tone`, and `## Language`,
   each containing non-empty plain text.
3. `## Constraints` contains one or more `- value` bullets.
4. `## Examples` contains two or three voice-example bullets.
5. `## Rubric` contains `- criterion: integer-weight` bullets totaling 100.
6. `## Threshold` contains an integer from 0 through 100.
7. `## Maximum Length` contains an integer from 1 through 10,000.
8. `## Model Route` defines exactly `research`, `copywriter`, and `critic`.
9. `## Publishing` defines the non-secret delivery route.

`## Banned Terms` and `## Required Hashtags` are optional bullet sections.

## Model route

Use `provider@model` so an operator can change either value without changing
Python:

```md
## Model Route
- research: gemini@gemini-3.1-flash-lite
- copywriter: groq@openai/gpt-oss-120b
- critic: github_models@openai/gpt-4o-mini
```

Supported providers are `gemini`, `groq`, and `github_models`. Copywriter and
Critic must use different providers. Legacy v0.1 values containing only the
provider still use the corresponding environment/default model.

## Publishing route

Safe default:

```md
## Publishing
- adapter: mock
- approval_required: true
```

Facebook Page:

```md
## Publishing
- adapter: facebook_page
- target_id: 123456789012345
- credential_ref: FACEBOOK_BRAND_PAGE_TOKEN
- approval_required: true
```

Threads:

```md
## Publishing
- adapter: threads
- target_id: 987654321012345
- credential_ref: THREADS_BRAND_USER_TOKEN
- topic_tag: Responsible AI
- topic_tag_candidates: Responsible AI | AI Tools | AI for Business
- trend_search: true
- approval_required: true
```

`credential_ref` is an uppercase environment-variable name, never a password
or token. Its value belongs in local `.env`, GitHub Actions Secrets, or a
production secret manager. A policy containing a lowercase/literal token fails
validation.

Threads topic-tag fields are optional:

- `topic_tag` is the fixed/fallback tag, without a leading `#`.
- `topic_tag_candidates` is a pipe-separated list of at most five unique,
  niche-relevant tags.
- `trend_search: true` compares recent tag-search result counts for the
  configured candidates and selects the most active one. It requires at least
  one candidate or fallback tag.

Topic-tag fields fail validation on `mock` and `facebook_page` policies.

`approval_required: true` sends an otherwise passing draft to human review.
The studio records approval without external network access. An operator then
uses **3 · Publish** or the guarded CLI:

```powershell
python run.py --publish-approved RUN_ID --publish-mode dry-run
python run.py --publish-approved RUN_ID --publish-mode live
```

`dry-run` is the default and does not resolve credentials or call Meta.

## Validation behavior

Unknown/duplicate headings, missing sections, invalid bullets, duplicate list
items, bad slugs, unsupported providers, malformed publishing targets, rubric
weights other than 100, or same-provider Copywriter/Critic routes fail with a
file-and-section-specific `PolicyParseError`.

Use `accounts/template.md` as the canonical starting point. To pause an
account without deleting its audit history, set `active: false`.

## Consumer contract

`load_policy(path)` returns `AccountPolicy`. The AI layer consumes a
`PolicyContext`; orchestration consumes model routes; the Publisher consumes
only `PublishingConfig`. SQLite freezes the complete policy for every run.
