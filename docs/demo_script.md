# Five-minute product demo

This is the short, repeatable product journey. Use `dry-run`; it proves the
approval and publishing guards without creating a real Facebook or Threads
post.

## Before recording

1. Start Streamlit against a clean demo database.
2. Keep the sidebar API-key fields blank to demonstrate system defaults, or
   paste temporary overrides while the fields are masked.
3. Open **Kết nối AI** and click **Kiểm tra 3 kết nối**. Start recording only
   after Research, Copywriter, and Critic all show ready.
4. Never show `.env`, Streamlit Secrets, request headers, or provider/Meta
   tokens.

## Recorded journey

1. Show the six-step header and the numbered tabs.
2. In **1 · Create content**, keep **Tạo mới từ prompt**, use the
   `responsible-ai-lab` channel, and enter the prepared topic/content prompt
   from `docs/demo_guide_vi.md`.
3. Click **Tạo bài bằng AI**. Show the generated post, Critic score,
   workflow state, Run ID, Request ID, and the original input lineage.
4. Open **2 · Review & approve**. Show score, violations, suggestions, current
   post, and source content. Enter an operator and approval note, then click
   **Approve and move to Publish**.
5. Point out the persistent success panel: action, new state, Run ID, Draft ID,
   operator, and next command.
6. Open **3 · Publish** and click **Run publishing dry-run**. Show the saved
   receipt and explain that dry-run neither reads a Meta token nor sends an
   external request.
7. Open **5 · Analytics**. Show run events, revisions, Critic results, audit
   actions, provider/model token usage, and **Data transfer**.
8. Download the uniquely named SQLite snapshot. Explain that one canonical
   operations database is used and at most 20 collision-safe local snapshots
   are retained.

## Optional extension

- Open **4 · Accounts & policies → Tạo kênh bằng form** to prove normal users
  can configure a channel without writing Markdown. The system generates the
  versioned policy behind the form.
- Show the Threads policy's fixed/candidate topic tags and `trend_search`.
- Run `python run.py --list-accounts` to validate every account without calling
  an AI provider.
- Repeat the dry-run CLI command for one approved Run ID and show idempotency:
  the same receipt is returned without another external request.

Only demonstrate `--publish-mode live` after replacing placeholder target IDs
with operator-owned Facebook Page/Threads User IDs and configuring valid Meta
tokens. Personal/clone-profile password or cookie automation is intentionally
unsupported.
