# ADR-0007: Threads is a second, independent publisher — not a branch in the first

**Status:** Accepted (2026-07-29)

## Context

A second content source exists: `/aws-shorts` in the content repository takes
an already-published LinkedIn post and derives Threads, X, and two video
scripts for the same day, saved as `shorts/day{NN}_{theme}.md`. It uses a
different file structure from `posts/day{NN}_{theme}.md` — platform sections
(`## Threads（日本語）`, `## X（English）`, …) instead of a bilingual body plus
glossary — and Threads is the only one of the four derivatives this project
has a publishing target for today.

Two designs were available: add Threads to the existing `handler.py`/
`linkedin.py` pair as a second branch, or add a second, parallel pipeline.

## Decision

**Threads is a second Lambda (`threads_handler.py`), its own EventBridge
Scheduler rule, its own IAM role, and its own Secrets Manager secret** —
structurally a sibling of the LinkedIn pipeline, not a feature inside it.
Both share the S3 content bucket and the DynamoDB state table, under a
distinct prefix and a distinct key namespace respectively:

| | LinkedIn | Threads |
| --- | --- | --- |
| Source prefix | `posts/` | `shorts/` |
| Parser | `parser.py` | `shorts_parser.py` |
| State key | `POST#DAY{NN}` | `THREADS#DAY{NN}` |
| Metric | `PostsPublished` | `ThreadsPostsPublished` |
| Lambda | `publisher-prod` | `publisher-prod-threads` |

The day number now identifies two independent publications, one per
platform. A shared key (`POST#DAY13`, say, used for both) would make claiming
one look like claiming the other; a distinct namespace makes that structurally
impossible rather than a rule to remember.

**The access token is refreshed automatically, unlike LinkedIn's.** ADR-0004
treats LinkedIn's 60-day expiry as a scheduled human event, because a
self-serve LinkedIn app has no refresh token at all. Threads is different: a
long-lived token can be exchanged for a new 60-day one at any point after its
first 24 hours, and doing so does not invalidate the token being replaced.
`threads_handler.py` refreshes at 14 days remaining — wide margin, since
refreshing early costs nothing — and writes the new token back to Secrets
Manager. The `threads-token-expiring` alarm (monitoring.tf) is deliberately
set at the same threshold as LinkedIn's for symmetry, but firing it means the
*automatic* refresh has been silently failing, not that a human's 60-day
calendar reminder is due. The IAM policy reflects this: the Threads Lambda
role grants `secretsmanager:PutSecretValue` on its own secret, which the
LinkedIn role never needed.

**Only the Threads section is parsed and published.** `shorts_parser.py`
reads `## Threads（日本語）` and nothing else. X and the two Shorts scripts sit
in the same source file for a human to copy by hand or feed into
`Shorts-Factory/` (a separate pipeline, in the AI-Operating-System
repository, that turns a script into an edited, subtitled video). Building a
publishing target for content nobody has decided to publish yet is exactly
the kind of premature scope this project has avoided elsewhere — see the
"planned" row for X in the README, unchanged by this ADR.

## Alternatives considered

- **Branch inside `handler.py`/`linkedin.py`.** Rejected: the two source
  formats parse differently, the token lifecycles differ enough that sharing
  the check-and-alert logic would need a platform flag running through it
  anyway, and a bug or a schedule change in one platform's code path should
  not be able to touch the other's. Two small, single-purpose functions read
  the same as one function that says "if platform == threads" halfway through.
- **One Lambda, invoked per platform via the EventBridge Scheduler payload.**
  Rejected: this only saves a `resource` block in Terraform, at the cost of
  every log line and every IAM policy needing to be read with "which
  platform was this invocation for?" in mind. EventBridge Scheduler already
  supports two independent rules at no extra cost.
- **Suffix the existing state key instead of a new prefix** (e.g.
  `POST#DAY13#THREADS`). Rejected: makes `POST#DAY13` ambiguous on its own —
  a lookup needs to already know which suffixes might exist for that day. A
  disjoint prefix (`THREADS#DAY13`) needs no such knowledge.

## Consequences

- Two Lambdas, two IAM roles, two schedules, two sets of alarms to read
  instead of one. Accepted, because the alternative bundles two independent
  failure domains together.
- The Threads Lambda's role is broader than LinkedIn's in one respect
  (`PutSecretValue`), which is the direct cost of the auto-refresh this ADR
  chose over ADR-0004's "alarm and wait for a human" approach — judged
  worthwhile because Threads makes the safer option available at all.
- Adding a third platform (X, if a publishing decision is ever made) has a
  template to follow: new prefix, new parser section, new state namespace,
  new Lambda. Whether that stays the right shape once there are three of them
  is a question for whichever ADR adds the third.
