# ADR-0002: Publication state lives in DynamoDB

**Status:** Accepted (2026-07-26)

## Context

Before automation, "has this been published?" was answered by where the file
sat: unpublished posts in `posts/`, published ones moved to `posts/Completed/`.
A separate index file recorded dates, but its dates turned out to be
generation dates, not publication dates.

Lambda cannot move files in a git repository on someone's laptop. Without a
single authoritative answer, the failure modes are double-posting and silent
gaps.

## Decision

DynamoDB holds publication state and is authoritative. One item per post:

| Attribute      | Purpose                                      |
| -------------- | -------------------------------------------- |
| `pk`           | `POST#DAY13`                                 |
| `status`       | `PENDING` / `PUBLISHED` / `FAILED`           |
| `posted_at`    | ISO-8601 timestamp of the successful publish |
| `linkedin_urn` | URN of the created post                      |
| `retry_count`  | attempts so far                              |

A conditional write on `status` makes publishing idempotent: a retried
invocation cannot post the same day twice.

## Alternatives considered

- **A JSON file in S3.** No conditional updates, so concurrent invocations can
  lose writes.
- **RDS.** Operationally and financially disproportionate for a table that
  holds a few hundred small items.

## Consequences

- The `posts/Completed/` convention is retired. Moving files no longer changes
  anything the publisher observes.
- `linkedin_urn` is stored on every success. It is what makes a follow-up
  action on an existing post possible later.
