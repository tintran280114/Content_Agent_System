# Account Policy Spec v0.1

An account is introduced through one UTF-8 Markdown file under `accounts/`.
No account-specific Python branch is allowed.

## Required sections

Every file must contain these level-two headings exactly once:

1. `## Account` with `- account_id: <lowercase-slug>` and
   `- spec_version: 0.1`.
2. `## Goal`, `## Audience`, `## Platform`, `## Tone`, and `## Language`, each
   containing non-empty plain text.
3. `## Constraints` and `## Examples`, each containing one or more `- value`
   bullets.
4. `## Rubric` containing `- criterion: integer-weight` bullets whose weights
   total 100.
5. `## Threshold` containing an integer from 0 through 100.
6. `## Maximum Length` containing an integer from 1 through 10,000.
7. `## Model Route` defining exactly `research`, `copywriter`, and `critic` as
   `- role: provider` bullets. Copywriter and Critic must differ.

`## Banned Terms` and `## Required Hashtags` are optional bullet sections. If
present, every hashtag must start with `#`.

Unknown/duplicate headings, missing sections, invalid bullets, duplicate list
items, invalid slugs, bad numeric ranges, rubric totals other than 100, and
same-provider Copywriter/Critic routes fail with a file-and-section-specific
`PolicyParseError`.

Use `accounts/template.md` as the canonical starting point. The checked-in
policies deliberately differ by goal, audience, platform, tone, constraints,
rubric, threshold, and maximum length.

## Consumer contract

`load_policy(path)` returns `AccountPolicy`. The AI layer consumes that object
through `PolicyContext.from_policy()` and selects the shared fields without
weakening the canonical parser contract. SQLite persists the complete
`AccountPolicy`, including its spec version and model route.
