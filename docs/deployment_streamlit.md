# Streamlit deployment

## Local operation

Open the guided studio:

```cmd
streamlit run streamlit_app.py
```

Use **1 · Create content → Tạo mới từ prompt** to choose a channel, enter a
topic, and describe the desired post in natural language. No Markdown is
required. Switch to existing-content mode only when repurposing, rewriting, or
summarizing pasted/uploaded source material. The UI and CLI run the same
orchestrator and default to `artifacts/content_agent.sqlite3`. Provider
credentials come from `.env` or session-only password fields.
Manual session values take priority; blank fields use `.env` or Streamlit
Secrets. Use **Kiểm tra 3 kết nối** before generation to distinguish a missing
or rejected key from blocked outbound network.

## Community Cloud settings

| Setting | Value |
|---|---|
| Repository file | `streamlit_app.py` |
| Python | `3.11` |
| Dependencies | root `requirements.txt` |
| Configuration | root `.streamlit/config.toml` |
| LLM secrets | `GEMINI_API_KEY`, `GROQ_API_KEY`, `GITHUB_MODELS_TOKEN` |

1. Push the chosen branch to GitHub.
2. Create a Community Cloud app and enter the branch manually if the dropdown
   has not refreshed.
3. Use root entrypoint `streamlit_app.py` and Python 3.11.
4. Add the three provider values in Streamlit Secrets.
5. Deploy; the studio can now generate a run from a topic or supplied content.
6. Optionally download and expand `content-agent-latest` from GitHub Actions,
   then upload its non-empty SQLite through **Analytics → Data transfer**.
7. Review, edit, approve, dry-run, and publish through the numbered tabs.
8. Download the unique SQLite snapshot before rebooting or redeploying. Names
   include a timestamp and random suffix; local rotation retains at most 20.

The uploaded file is validated for SQLite format, integrity, size, and required
tables before replacement.

## Persistence boundary

Community Cloud does not guarantee local-file persistence. GitHub Actions also
runs on another machine. Snapshot upload/download is therefore an explicit MVP
handoff, not a shared cloud database. For durable multi-user synchronization a
managed store would be required, and that is outside the sprint scope.

Official references:

- https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy
- https://docs.streamlit.io/develop/concepts/connections/connecting-to-data
- https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule
