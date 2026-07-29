# Content request contract

An account policy and content request are different Markdown inputs with
different lifetimes and purposes. The Streamlit content flow accepts exactly
one `.md`/`.markdown` file per run. Its `# Topic`, `# Instructions`, `# Source`
or `# Content` sections map into the canonical `ContentRequest`.

| Input | Meaning | Example | Lifetime |
|---|---|---|---|
| Account policy | Permanent account behavior | voice, audience, banned terms, rubric, publisher | reused for every run |
| Content Markdown | Topic, brief, source or final post | `content-generate.md` | one run |

Account policies are stored in `accounts/*.md` and discovered automatically.
Content Markdown is uploaded in **Create content**. CLI `--content-file` remains
available for backward-compatible batch jobs and is never scanned as an account
policy.

## Content tasks

| Task | Source required | Behavior |
|---|---:|---|
| `create` | No | Create a new post from the topic, policy, brief, and optional references |
| `repurpose` | Yes | Adapt the source for the policy platform and audience |
| `rewrite` | Yes | Improve the source while preserving its meaning |
| `summarize` | Yes | Produce a concise social post from the source |

## Frozen handoff

```text
ContentRequest
  request_id
  mode: generate | publish
  topic
  instructions
  task
  source_type: none | pasted | file
  source_name
  source_content
      |
      + AccountPolicy
      v
ResearchBrief -> DraftPost -> Rule Critic -> LLM Critic -> Review -> Publisher
```

The same `request_id` is attached to the Research brief and Draft post. The
complete request is stored as a SQLite `content_request` artifact so reviewers
can compare the generated post with the original topic, brief, and source.
Older snapshots without this artifact remain readable and fall back to their
stored topic.

## Safety and quota behavior

- Operator instructions are trusted directions.
- Source content is untrusted data. Agents are explicitly told not to execute
  commands embedded in source material.
- The LLM Critic receives the request and Research brief so it can flag
  omissions, meaning changes, and unsupported claims.
- Source/final content is limited to 30,000 characters to protect free-tier
  context and quota. The one-file UI accepts UTF-8 `.md`/`.markdown` up to
  100 KB.
- API keys and social tokens must never be placed in topic, instructions,
  source content, or account policy.

## CLI examples

Create from topic only:

```powershell
python run.py --account responsible-ai-lab `
  --topic "Responsible AI review"
```

Repurpose a Markdown source:

```powershell
python run.py --account responsible-ai-lab `
  --topic "Offline feature launch" `
  --instructions "Use a practical three-step angle and one CTA" `
  --content-file release-notes.md `
  --content-task repurpose
```

Summarize short inline content:

```powershell
python run.py --account community-learning `
  --topic "Workshop recap" `
  --content "The workshop covered policy, review, and accountability." `
  --content-task summarize
```
