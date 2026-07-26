# ADR-0004: Treat token expiry as a scheduled event, not an incident

**Status:** Accepted (2026-07-26)

## Context

LinkedIn issues refresh tokens only to approved Marketing Developer Platform
partners. A self-serve application receives an access token valid for 60 days
and nothing else.

Sixty days is shorter than the content backlog this pipeline is meant to
publish. Expiry is not a risk to mitigate; it is a certainty to schedule.

The failure mode that matters is the silent one: the token expires, every
invocation fails with 401, and nobody notices for a week.

## Decision

- Store the token in Secrets Manager together with the client credentials.
- **Ask LinkedIn for the expiry rather than recording it.** Every run calls
  `POST /oauth/v2/introspectToken`, which returns the real `expires_at`, the
  token `status`, and the granted scopes. A hand-entered expiry is wrong the
  first time somebody re-authorizes and forgets to update it, and a wrong
  expiry means the alarm fires late or not at all — reintroducing exactly the
  silent failure this ADR exists to prevent. The stored `expires_at` remains
  as a fallback for deployments without client credentials.
- Treat `active: false` as fatal, not just expiry. LinkedIn reserves the right
  to revoke tokens early for technical or policy reasons, so "not expired" and
  "usable" are different claims.
- Verify `w_member_social` is present before doing any work. A token missing
  the scope cannot publish, and failing on the scope check produces a clearer
  alert than a 403 from the posting call.
- A daily check publishes a CloudWatch metric for days remaining, with an
  alarm at 7 days that notifies through SNS.
- Any 401 from LinkedIn is treated as an alerting condition, not a retry.
  Retrying an expired token only produces more 401s.
- Re-authorization is a documented runbook: `docs/setup-linkedin-app.md`.

## Alternatives considered

- **Apply for MDP partner status** to obtain refresh tokens. Not realistic for
  a personal project.
- **Let it fail and notice eventually.** This is the default, and it is how
  integrations like this quietly die.
- **Record the expiry by hand and keep the client secret out of the function.**
  Smaller blast radius if the secret or the execution role leaks, but it puts
  the accuracy of the only expiry warning back into a manual step. The client
  secret alone cannot mint a member token — the authorization code flow needs
  the member's consent screen — so the added exposure is limited.

## Consequences

- Full automation has a bounded lifetime. The honest description of this
  system is "automated publishing with a scheduled manual re-authorization",
  not "fully automated forever".
- Secrets Manager costs about USD 0.40 per secret per month. It is not free,
  and the README says so.
