# Streamlit deployment handoff

## Local persistent mode

```cmd
set CONTENT_AGENT_DB=artifacts\content_agent.sqlite3
streamlit run streamlit_app.py
```

This is the recommended operator mode because the CLI, dashboard actions, and
mock Publisher all use the same durable local SQLite file.

## Community Cloud

Streamlit Community Cloud deploys from GitHub and runs the entrypoint from the
repository root. The deployment values are:

| Setting | Value |
|---|---|
| Entrypoint | `streamlit_app.py` |
| Python | `3.11` |
| Dependency file | root `requirements.txt` |
| Configuration | root `.streamlit/config.toml` |
| Secrets template | `.streamlit/secrets.toml.example` |

Deployment steps:

1. Merge the app to a GitHub branch visible to the Streamlit account.
2. Open `share.streamlit.io`, create an app, and select repo/branch/entrypoint.
3. Open Advanced settings, select Python 3.11, and paste filled TOML secrets.
4. Deploy and inspect the Cloud logs.
5. Download the latest `content-agent-snapshot-*` artifact from GitHub Actions.
6. Upload its SQLite file through the dashboard sidebar.
7. After review actions, download the updated snapshot before reboot/hibernation.

Official references:

- https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy
- https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/file-organization
- https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management

## Honest storage boundary

Community Cloud is the free dashboard host, not the batch scheduler or durable
database. The MVP therefore uses explicit SQLite snapshot upload/download.
Automatic bidirectional cloud database synchronization, authentication, and a
production datastore are deferred by the sprint scope. Do not assume a local
Cloud SQLite file survives every reboot or app replacement.
