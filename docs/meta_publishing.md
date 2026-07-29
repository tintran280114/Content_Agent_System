# Facebook Page and Threads publishing

## Security boundary

- Do not store a Facebook password, Threads password, app secret, or access
  token in `accounts/*.md`.
- Markdown stores only public target IDs and `credential_ref`.
- Tokens are sent in the `Authorization: Bearer ...` header and are excluded
  from URLs, SQLite records, logs, and error messages.
- `python run.py --list-accounts` shows the referenced environment-variable
  name and present/missing status, never the secret value.
- `--publish-mode live` is an explicit operator gate. Every other path is mock
  or dry-run.
- The Page/User IDs bundled in the example account policies are placeholders.
  Replace them with operator-owned IDs before any live command.

## Facebook Page setup

1. Create/configure a Meta app and Facebook Login flow.
2. Obtain a User access token with the Page permissions required by the app,
   commonly `pages_show_list`, `pages_read_engagement`, and
   `pages_manage_posts`.
3. Retrieve the Page access token and Page ID through `/me/accounts`.
4. Put the Page token in the environment variable named by `credential_ref`.
5. Dry-run the approved run, then use live mode.

The adapter publishes text through:

```text
POST https://graph.facebook.com/{version}/{page_id}/feed
Authorization: Bearer {page_access_token}
message={rendered_post}
```

This project targets Facebook Pages, not password-based automation of personal
profiles. Personal or clone-account password/cookie/session automation is not
supported; it is brittle, unsafe for the account, and outside the official Page
publishing flow.

## Threads setup

1. Configure Threads OAuth for the app.
2. Request `threads_basic` and `threads_content_publish`. Also request
   `threads_keyword_search` when a policy enables `trend_search`.
3. Store the Threads User access token in the referenced environment variable.
4. Dry-run before enabling live mode.

The adapter performs the official two-step text flow:

```text
POST /{threads_user_id}/threads
POST /{threads_user_id}/threads_publish
```

### Topic/community tag selection

The Threads create-container request supports one `topic_tag`. Configure a
fixed tag, or a small candidate set:

```md
## Publishing
- adapter: threads
- target_id: YOUR_THREADS_USER_ID
- credential_ref: THREADS_RESPONSIBLE_AI_TOKEN
- topic_tag: Responsible AI
- topic_tag_candidates: Responsible AI | AI Tools | AI for Business
- trend_search: true
- approval_required: true
```

When `trend_search` is enabled, the publisher calls Threads keyword search in
`TAG` + `RECENT` mode for each configured candidate, considers results from the
last 24 hours, and selects the candidate with the largest returned result
count. The list is capped at five to bound API usage. This is a trend-aware
choice within the account's approved niche, not a claim to represent a global
Threads trending feed. The selected tag is saved in the publish receipt.

If the app lacks `threads_keyword_search`, either grant that permission or set
`trend_search: false`; the fixed `topic_tag` still works with the content
publishing flow.

### OAuth, encrypted storage, and automatic rotation

The sidebar **Facebook & Threads** flow accepts a Meta OAuth authorization
code, exchanges it for a short-lived Threads token, then exchanges that token
for a long-lived token. It stores only the encrypted long-lived token in
`CONTENT_AGENT_TOKEN_STORE`; the Fernet key and Threads App Secret stay in
environment variables or deployment secrets.

```dotenv
THREADS_APP_ID=
THREADS_APP_SECRET=
THREADS_REDIRECT_URI=http://localhost:8501
THREADS_TOKEN_REFRESH_DAYS=7
CONTENT_AGENT_TOKEN_ENCRYPTION_KEY=
CONTENT_AGENT_TOKEN_STORE=artifacts/meta_tokens.enc
```

Before each Threads publish, `ThreadsTokenManager` checks the recorded expiry.
Inside the configured refresh window it calls
`GET /refresh_access_token?grant_type=th_refresh_token` and atomically rotates
the encrypted record. A transient refresh network error falls back to the
still-valid token; a rejected or expired token requires OAuth reconnect.

A manually supplied long-lived token can still be used for the browser session.
Supplying `{credential_ref}_EXPIRES_AT` in ISO-8601 format enables proactive
refresh. Without an encryption key, a refreshed value cannot survive an app
restart.

For a new account, create a new uppercase `credential_ref` in its account
policy. Never put the token in Markdown. An HTTP 401/403 is reported as
`publish_authentication`; investigate any pending delivery reservation before
reconnecting or retrying.

### Scheduled automatic publishing

The bundled GitHub Actions batch accepts Meta tokens from repository Secrets
and reads `CONTENT_AGENT_PUBLISH_MODE` from a repository Variable. Its default
is `dry-run`. Unattended live delivery requires all of these deliberate
changes:

1. Replace the example target ID with the operator-owned Page or Threads User
   ID.
2. Add the exact `credential_ref` as a GitHub Actions Secret.
3. Complete an offline test and a dry-run receipt.
4. Set repository Variable `CONTENT_AGENT_PUBLISH_MODE=live`.
5. Set that policy's `approval_required: false`.

Leave `approval_required: true` for a review-first account. The scheduler will
stop at human review and will not post it automatically.

Official Meta references:

- [Threads API collection](https://www.postman.com/meta/threads/overview)
- [Threads create and publish requests](https://www.postman.com/meta/threads/documentation/dht3nzz/threads-api)
- [Threads keyword search request](https://www.postman.com/meta/threads/request/34203612-b3b2c12a-7ce6-4d86-a3c6-6d31e3b66ea1)
- [Facebook API collection](https://www.postman.com/meta/facebook/overview)

## Reliability

Both adapters:

- reserve a deterministic idempotency key before external delivery;
- retry HTTP 429 and 5xx responses with bounded exponential backoff;
- never reuse the content rewrite budget for transport retries;
- persist status, destination, attempt count, HTTP status, remote post ID, and
  selected Threads topic tag;
- leave failed or uncertain delivery in a traceable state for manual handling.

Dry-run and live delivery use separate idempotency reservations, so the same
approved draft can be validated first and then published once. Repeating either
command returns its existing receipt and does not make another request.

If a process stops after reserving a delivery but before receiving a response,
the reservation remains blocked instead of risking a duplicate post.
