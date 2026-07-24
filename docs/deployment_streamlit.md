# Streamlit deployment

## Local operation

Generate content with the CLI, then open the review surface:

```cmd
python run.py --all --topic "How small teams can use AI responsibly"
streamlit run streamlit_app.py
```

Both default to `artifacts/content_agent.sqlite3`. Streamlit performs no LLM
calls and needs no provider credentials.

## Community Cloud settings

| Setting | Value |
|---|---|
| Repository file | `streamlit_app.py` |
| Python | `3.11` |
| Dependencies | root `requirements.txt` |
| Configuration | root `.streamlit/config.toml` |
| LLM secrets | none |

1. Push the chosen branch to GitHub.
2. Create a Community Cloud app and enter the branch manually if the dropdown
   has not refreshed.
3. Use root entrypoint `streamlit_app.py` and Python 3.11.
4. Deploy; an empty SQLite file is created automatically.
5. Download and expand `content-agent-latest` from a GitHub Actions run.
6. Upload `content_agent.sqlite3` through **Cloud snapshot handoff**.
7. Review, edit, approve, or reject queued items.
8. Download the reviewed SQLite evidence before rebooting or redeploying.

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
