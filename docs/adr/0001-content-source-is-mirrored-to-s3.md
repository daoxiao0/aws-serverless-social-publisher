# ADR-0001: The content repository stays the source of truth, mirrored to S3

**Status:** Accepted (2026-07-26)

## Context

Posts are written and reviewed in a private knowledge repository, which is
also the source for other publishing channels. The Lambda function needs to
read the post scheduled for today.

Reading from GitHub directly would mean putting a GitHub token in the
function's environment — a second credential to rotate — and accepting
GitHub's API rate limits on the publishing path.

## Decision

The knowledge repository remains the single source of truth. A GitHub Actions
workflow mirrors the posts directory to S3 on push. Lambda reads only from S3.

## Alternatives considered

- **Lambda reads GitHub via API.** Adds a credential, adds a rate limit, and
  couples publishing availability to GitHub's.
- **S3 becomes the source of truth.** Splits content away from the repository
  where it is authored and reviewed, and every other channel would then need
  to read from S3 too.

## Consequences

- S3 is a cache, never edited by hand. Anything there can be rebuilt from the
  repository.
- Publishing keeps working during a GitHub outage, as long as the mirror ran.
- The mirror job authenticates with GitHub OIDC rather than a long-lived
  access key.
