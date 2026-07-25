# Content request contract

An account policy and source content are different inputs. They may both be
Markdown files, but they have different lifetimes and purposes.

Normal Streamlit users do not need to create either file. The default Quick
Composer asks for a channel/profile, topic, and natural-language description
of the desired post. The guided channel form generates the account policy
behind the scenes. File inputs remain available for source transformation and
advanced admin handoff.

| Input | Meaning | Example | Lifetime |
|---|---|---|---|
| Account policy | Permanent account behavior | voice, audience, banned terms, rubric, publisher | reused for every run |
| Topic | Subject Research Agent should investigate | `Offline mode launch` | one run |
| Writing brief | Trusted operator directions | `Use three steps and end with a question` | one run |
| Source content | Reference material the post must use | release note, article, transcript, old post | one run |

Account policies are stored in `accounts/*.md` and discovered automatically.
Source `.md`/`.txt` files are uploaded in **Create content** or supplied with
`--content-file`; they are never scanned as account policies.

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
- Source content is limited to 30,000 characters to protect free-tier context
  and quota. Accepted upload types are UTF-8 `.md` and `.txt`.
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
