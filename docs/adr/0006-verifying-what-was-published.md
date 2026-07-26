# ADR-0006: Assume publishing can fail without saying so

**Status:** Accepted (2026-07-26)

## Context

Two defects reached production on the first day, and neither produced an
error.

**The post was truncated.** LinkedIn's `commentary` field is not plain text.
It is "little text", where `( ) [ ] { } @ < > | * _ ~ \` are reserved and must
be backslash-escaped — the documentation is explicit that this applies even
when the characters are not being used as markup. An unescaped one is not
rejected. The API returns `201 Created` and drops everything from that
character onward. The first post went out cut off at its first parenthesis,
and all sixty queued posts contained at least one reserved character.

**The wrong post was selected.** The next post to publish was looked up in
DynamoDB by its storage key, `posts/day13_title.md`, while rows are keyed
`POST#DAY13`. The lookup missed every time, so every post looked unpublished
and the run always chose the first file. This was invisible while the first
file happened to be the right answer. Once earlier posts returned to the
directory, each run selected an already-published post, failed to claim it,
and returned `{"published": false}` — a clean exit, no exception, no alarm.

Neither was detectable from inside the system. Reading a member's own posts
back requires `r_member_social_feed`, which is partner-gated: `GET
/rest/posts/{urn}` returns 403. **This application cannot see what it
published.**

## Decision

Treat successful-looking outcomes as unreliable, and watch for silence
instead.

- Escape reserved characters in the API client, immediately before the call.
  It is an encoding concern of this API, not a property of the content.
- Emit a `PostsPublished` metric on each successful publish, and alarm when
  three consecutive days produce none. Three days rather than one, so a
  weekend on a weekday schedule does not fire it.
- Accept that content correctness — whether the published text reads as
  intended — is verified by a human, because nothing else can.

## Alternatives considered

- **Read the post back and compare.** The obvious check, and unavailable:
  partner-gated. Worth revisiting if that access is ever granted.
- **Alarm on `published: false`.** Too noisy: an empty backlog and an already
  claimed post are both legitimate. The absence of publishing over days is the
  signal, not any single run.
- **Trust the 201.** This is what was being done, and it is what let a
  truncated post look like a success.

## Consequences

- Running out of backlog raises the alarm too. That is intended: it is worth
  knowing.
- The silent-stall class of failure is now detected within three days rather
  than never. Truncation and similar content defects are still only caught by
  reading a published post.
