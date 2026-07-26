# ADR-0005: Trust the content repository by ID, not by name

**Status:** Accepted (2026-07-26)

## Context

The CI job that mirrors content into S3 authenticates with GitHub OIDC. The
usual trust policy matches the token's subject claim by name:

```
"token.actions.githubusercontent.com:sub": "repo:owner/repo:*"
```

The first run failed with `Not authorized to perform
sts:AssumeRoleWithWebIdentity` even though the provider, the audience, and the
repository name were all correct. Printing the token's claims showed why:

```
"sub": "repo:owner@286922810/repo@1281356965:ref:refs/heads/main"
```

GitHub now issues subjects carrying immutable numeric IDs alongside the names.
The name-only pattern does not match, and the failure message says nothing
about which claim was compared.

The reason the format changed matters here. Account and repository names can be
released and re-registered by anyone. Under the old format, a trust policy
naming an account that its owner had abandoned could be satisfied by whoever
claimed that name next.

This is not hypothetical for this project: the account was renamed the same day
this role was created, releasing the previous name.

## Decision

Match on the immutable IDs and treat the names as wildcards:

```
"token.actions.githubusercontent.com:sub": "repo:*@286922810/*@1281356965:*"
```

The pattern is exposed as `mirror_subject_patterns`, a list, defaulting to the
legacy name-derived form so that repositories still issuing the old format work
without configuration.

## Alternatives considered

- **Match both forms**, name-based and ID-based, as a list. Commonly
  recommended for migrations, but it keeps the name-based pattern alive, which
  is the exact weakness the ID format closes. Reasonable while migrating a
  fleet; not reasonable for one repository that already emits the new format.
- **Pin names and IDs together** — `repo:owner@286922810/repo@1281356965:*`.
  Equally secure, but a later rename breaks deployment for no benefit: the IDs
  already identify the repository unambiguously.

## Consequences

- Renaming the account or the repository does not break the mirror.
- A released account name re-registered by somebody else cannot mint a token
  this role will accept.
- The IDs are opaque, so the tfvars entry needs a comment saying whose they
  are. `gh api repos/{owner}/{repo} --jq '{repo: .id, owner: .owner.id}'`
  recovers them.
