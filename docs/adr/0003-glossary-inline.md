# ADR-0003: The glossary is published inline, not as a comment

**Status:** Accepted (2026-07-26)

## Context

Each source post has a body and a short glossary. The established manual
routine was to publish the body, then add the glossary as the first comment.

Reproducing that through the API requires creating a comment. Third-party
guides claim `w_member_social` is enough for this. It is not. Measured against
the live API on 2026-07-26:

```
POST /rest/posts                          -> 201 Created
POST /rest/socialActions/{urn}/comments   -> 403 ACCESS_DENIED
    "Not enough permissions to access: partnerApiSocialActions.CREATE"
```

The official permission table for the Comments API lists
`w_member_social_feed`, a Community Management API scope, not
`w_member_social`. Community Management access requires review even at the
development tier.

## Decision

Append the glossary to the post body and publish once.

The two sections stay separate in the source files, and `render()` takes an
`inline_glossary` flag. If the permission ever becomes available, the change
is one configuration value — no content migration.

## Alternatives considered

- **Apply for Community Management API access.** Uncertain outcome for a
  personal project, and it would block the whole pipeline on a review queue.
- **Notify a human to paste the comment manually.** Keeps the original layout
  but leaves a daily manual step, which defeats the purpose.
- **Drop the glossary.** Discards content that is already written and useful.

## Consequences

- Posts are longer. Measured across 48 real posts, the rendered result ranges
  from 838 to 1127 characters, against a 3000-character limit.
- `render()` also strips Markdown emphasis, since LinkedIn does not interpret
  Markdown and would display the asterisks.
