# Setting up a Threads app and getting an access token

Free, self-serve, no review process for the two permissions this project
needs. Budget about 30 minutes the first time.

If you only need to re-populate the secret after rotating credentials, skip
to [Storing the token](#storing-the-token).

---

## What you get, and what you do not

| Capability | Available? |
| --- | --- |
| Post to your own account | **Yes** — `POST /{user_id}/threads` + `POST /{user_id}/threads_publish` |
| Refresh the token before it expires | **Yes** — `GET /refresh_access_token`, any time after the token is 24h old |
| Resolve your user id | **Yes** — `GET /me` |
| **Read your own posts back** | Not used by this project; not verified |
| **Delete a post via the API** | Not documented as available. `check_threads_access.py` does not create a real test post because of this — see the script's docstring |
| Rate limit | 250 API-published posts per 24 hours per user |

The refreshable token is the one meaningful way this integration differs
from the LinkedIn one — see [ADR-0007](adr/0007-threads-is-a-second-independent-publisher.md).
A self-serve LinkedIn app cannot refresh at all (ADR-0004); a Threads app can,
and this project's Lambda does so automatically well before expiry, so
routine operation should never require a human to re-authorize by hand.

## Prerequisites

- An Instagram account with a Threads profile, and the ability to log in to
  <https://threads.net> with it.
- A Meta Developer account at <https://developers.facebook.com/>.

## 1. Create the app

<https://developers.facebook.com/apps/creation/> → **Create App**.

| Field | Value |
| --- | --- |
| App name | anything |
| Use case | Other |
| App type | Business |

## 2. Add the Threads API product

**Use Cases** (left menu) → **Add** → **Access the Threads API**.

## 3. Add yourself as a Threads tester

**App roles** → **Roles** → **Threads Testers** → **Add**, enter your Threads
username. Status shows **Pending**.

## 4. Accept the invitation as the account owner

On the account that will publish, in the Threads app itself: **Settings** →
**Website permissions**, find this app, and approve it. Grant all of:

- Access and display your Threads information
- Create and share posts
- Manage replies and quotes
- Read replies
- Manage insights

Only the first two are used by this project; approving the rest costs
nothing and avoids a second round trip if a later feature needs them. Once
approved, the tester status in Meta Developer flips to **Accepted**.

## 5. Generate the token

Meta Developer → your app → **Threads API** → **User Token Generator** →
**Generate Long-lived Access Token**.

The token is valid for **60 days**. Copy it now; it is shown once.

## 6. Resolve the user id

```
GET https://graph.threads.net/v1.0/me?fields=id,username&access_token=YOUR_TOKEN
```

Returns `{"id": "...", "username": "..."}`. The `id` is what this project
calls `user_id`; it does not change on refresh, so it only needs collecting
once.

## 7. Store the token

For local testing, keep it outside any git repository:

```bash
# macOS / Linux
printf '%s' 'YOUR_TOKEN' > ~/.threads_token
chmod 600 ~/.threads_token
```

```powershell
# Windows PowerShell
Set-Content -Path "$env:USERPROFILE\.threads_token" -Value 'YOUR_TOKEN' -NoNewline
```

### Storing the token

For deployment, the token belongs in Secrets Manager together with the user
id and the expiry this project will use as a fallback until its first
automatic refresh:

```json
{
  "access_token": "YOUR_TOKEN",
  "user_id": "YOUR_USER_ID",
  "expires_at": "2026-09-27T00:00:00Z"
}
```

```bash
aws secretsmanager put-secret-value \
  --secret-id social-publisher-prod/threads-token \
  --secret-string file://secret.json   # then delete the file
```

Set `expires_at` to 60 days from generation. After that, `threads_handler.py`
maintains it: every invocation refreshes the token once fewer than 14 days
remain and overwrites this same secret with the new token and its real
expiry, so the hand-written date only matters until the first refresh.

`.gitignore` in this repository already excludes `.threads_token`, `.env`,
and `*.tfvars`. Verify with `git status` before your first commit anyway.

## 8. Confirm it works

```bash
python scripts/check_threads_access.py
```

Resolves the account identity and exercises the refresh call — see the
script's docstring for why it stops there instead of also posting.

**Posting itself is verified by the pipeline's own dry run**, not by this
script: deploy with `threads_dry_run = true` (the default), invoke the
Lambda by hand, and read the CloudWatch log for the rendered text and a
`dry run, claim released` outcome. Only after that looks right should
`threads_dry_run` become `false`.

---

## Troubleshooting

**Tester status stuck on Pending.**
Re-check step 4 — the approval happens inside the Threads app, on the
account that will publish, not in Meta Developer.

**`OAuthException` on every call.**
The token expired, or was generated before permissions were approved.
Re-generate it (step 5); tokens carry the permissions they had at creation.

**403 on `POST /{user_id}/threads`.**
The "Create and share posts" permission was not granted in step 4, or the
token predates granting it.

**Refresh returns `OAuthException` immediately after generating the token.**
Expected for the first 24 hours — Meta does not allow refreshing a token
that young. Wait, or use the fresh token as-is; it is already valid for 60
days.

## References

- [Threads API overview](https://developers.facebook.com/docs/threads)
- [Get long-lived access tokens](https://developers.facebook.com/docs/threads/get-started/long-lived-tokens)
- [Refresh a long-lived access token](https://developers.facebook.com/docs/threads/get-started/long-lived-tokens#refresh-a-long-lived-token)
