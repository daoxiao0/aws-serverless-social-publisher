# Setting up a LinkedIn app and getting an access token

Everything here can be done with the free, self-serve tier. No review process,
no partner status, no cost. Budget about 40 minutes the first time.

If you only want to re-authorize an expired token, skip to
[Renewing an expired token](#renewing-an-expired-token).

---

## What you get, and what you do not

Read this before you start. Two of these surprise people late, after the code
is already written.

| Capability | Available? |
| --- | --- |
| Post to your own profile | **Yes** — `POST /rest/posts` |
| Delete your own post | **Yes** — `DELETE /rest/posts/{urn}` |
| Read your own identity | **Yes** — `GET /v2/userinfo` |
| Check when the token expires | **Yes** — `POST /oauth/v2/introspectToken` |
| **Read your own posts back** | **No** — partner-gated, so you cannot verify what you published |
| **Comment on a post** | **No** — partner-gated, see below |
| **Refresh token** | **No** — partner-gated, see below |
| Rate limit | 150 requests per day per member |

**Comments.** Several third-party guides state that `w_member_social` allows
commenting. It does not. The official permission table for the Comments API
lists `w_member_social_feed`, which belongs to the Community Management API
and requires review. Measured against the live API on 2026-07-26:

```
POST /rest/posts                          -> 201 Created
POST /rest/socialActions/{urn}/comments   -> 403 ACCESS_DENIED
    "Not enough permissions to access: partnerApiSocialActions.CREATE.20260701"
```

You can reproduce this yourself with `scripts/check_access.py` once you have a
token. See [ADR-0003](adr/0003-glossary-inline.md) for how this project works
around it.

**Refresh tokens.** LinkedIn issues them only to approved Marketing Developer
Platform partners. A self-serve app gets an access token valid for **60 days**
and nothing else. Plan for re-authorization rather than discovering it through
a week of silent 401s — see [ADR-0004](adr/0004-access-token-lifecycle.md).

---

## 1. Create a LinkedIn Page

Every app must be associated with a LinkedIn Page, which acts as its
publisher. If you do not already have one, create it at
<https://www.linkedin.com/company/setup/new>.

A page for your own practice or personal brand is fine. Because you become its
super admin, you can approve your own app in step 3 without involving anyone
else.

## 2. Create the app

<https://www.linkedin.com/developers/apps/new>

| Field | Value |
| --- | --- |
| App name | anything |
| LinkedIn Page | the page from step 1 |
| App logo | required |

## 3. Verify the app

**Settings** tab -> **Verify**. This generates a URL. Open that URL yourself
and approve it: you are the page super admin, so no one else is involved.

Do not skip this. Products cannot be added to an unverified app, and step 4
will simply not offer them.

## 4. Add two products

**Products** tab. Both are self-serve and take effect immediately.

| Product | Grants | Why you need it |
| --- | --- | --- |
| Share on LinkedIn | `w_member_social` | creating posts |
| Sign In with LinkedIn using OpenID Connect | `openid`, `profile` | resolving your person URN |

The second one is easy to skip and the mistake is not obvious: without a
person URN there is no value for the `author` field, so posting fails even
though you hold a valid posting permission.

Anything with a **Request access** button — Community Management API,
Marketing Developer Platform — is review-gated. You do not need it, and
requesting it is not a shortcut to comment permissions.

## 5. Register a redirect URL

**Auth** tab -> **OAuth 2.0 settings** -> **Authorized redirect URLs**.

Add any URL you control. If you have no callback endpoint, this works:

```
https://oauth.pstmn.io/v1/callback
```

The token generator in the next step needs at least one entry present.

## 6. Generate the token

**Auth** tab -> **OAuth 2.0 tools** -> **Create token**.

Select all three scopes:

```
openid   profile   w_member_social
```

Approve the consent screen. The access token appears in the dialog. It is
valid for 60 days, and there is no refresh token — that is expected, not a
misconfiguration.

While you are on the **Auth** tab, also copy the **Client ID** and the
**Primary Client Secret**. They are not needed to publish, but they are what
lets the pipeline ask LinkedIn when the token really expires instead of
trusting a date somebody typed in by hand.

## 7. Store the token

For local testing, keep it outside any git repository:

```bash
# macOS / Linux
printf '%s' 'YOUR_TOKEN' > ~/.linkedin_token
chmod 600 ~/.linkedin_token
```

```powershell
# Windows PowerShell
Set-Content -Path "$env:USERPROFILE\.linkedin_token" -Value 'YOUR_TOKEN' -NoNewline
```

For deployment, the token belongs in Secrets Manager together with the client
credentials:

```json
{
  "access_token": "YOUR_TOKEN",
  "client_id": "YOUR_CLIENT_ID",
  "client_secret": "YOUR_CLIENT_SECRET",
  "expires_at": "2026-09-24T00:00:00Z"
}
```

```bash
aws secretsmanager put-secret-value \
  --secret-id linkedin/access-token \
  --secret-string file://secret.json   # then delete the file
```

`expires_at` is a fallback. When the client credentials are present the
pipeline calls token introspection and uses the expiry LinkedIn reports, so
the hand-written date stops mattering — which is the point, because a
hand-written date is wrong the first time somebody re-authorizes and forgets
to update it.

`.gitignore` in this repository already excludes `.linkedin_token`,
`.linkedin_client`, `.env`, and `*.tfvars`. Verify with `git status` before
your first commit anyway — it costs a second and a leaked token cannot be
un-leaked.

## 8. Confirm it works

```bash
python scripts/check_access.py
```

It resolves your identity, creates a throwaway post visible to connections
only, tries to comment on it, and deletes the post. The token is never
printed. Expect `post: OK` and `comment: BLOCKED` — that is a correctly
configured self-serve app, not a failure.

---

## Renewing an expired token

Once every 60 days, or whenever the API starts returning 401:

1. **Auth** tab -> **OAuth 2.0 tools** -> **Create token**
2. Same three scopes, approve again
3. Update the secret:

```bash
aws secretsmanager put-secret-value \
  --secret-id linkedin/access-token \
  --secret-string file://secret.json   # same fields, new access_token
```

Nothing else changes. The app, the products, the page verification, and the
client credentials all persist; only the token expires. If introspection is
configured you do not need to touch `expires_at` at all — the next run reads
the real value from LinkedIn.

---

## Troubleshooting

**Products tab offers nothing but "Request access".**
The app is not verified. Return to step 3.

**401 Unauthorized on every call.**
The token expired. Sixty days pass faster than expected.

**403 on `POST /rest/posts`.**
The Share on LinkedIn product is missing, or the token was minted before you
added it. Tokens carry the scopes they had at creation time, so add the
product first, then generate a new token.

**400 with a message about `LinkedIn-Version`.**
Versioned endpoints under `/rest/` require a `LinkedIn-Version: YYYYMM`
header. Only the legacy `/v2/` endpoints work without it.

**403 on the comments endpoint.**
Expected. See the top of this document.

## References

- [Share on LinkedIn](https://learn.microsoft.com/en-us/linkedin/consumer/integrations/self-serve/share-on-linkedin)
- [Refresh tokens](https://learn.microsoft.com/en-us/linkedin/shared/authentication/programmatic-refresh-tokens)
- [Comments API permissions](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/comments-api)
- [Associating an app with a LinkedIn Page](https://www.linkedin.com/help/linkedin/answer/a548360)
