"""Parse a Threads-derivative post out of an /aws-shorts output file.

Source files live in the content repository, one per day, and hold four
platform derivatives of the same LinkedIn post (see /aws-shorts in the
content repository)::

    # ■ Day16 Lambda環境変数（派生元: posts/day16_Lambda環境変数.md）

    ## Threads（日本語）

    ...Japanese body...

    ## X（English）

    ...

This project publishes the Threads section only. X and the two Shorts video
scripts are recorded in the same file for a human to use when recording, not
because a publishing target for them exists yet — see ADR-0007.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_HEADING = re.compile(r"^#[ \t]*■[ \t]*Day(\d+)[ \t]+(.+?)[ \t]*$", re.MULTILINE)
_SECTION = re.compile(r"^##[ \t]+(.+?)[ \t]*$", re.MULTILINE)

THREADS_SECTION = "Threads（日本語）"


class ShortsFormatError(ValueError):
    """The source file does not match the expected structure."""


def threads_state_key(day: int) -> str:
    """The DynamoDB partition key for a given day's Threads post.

    A distinct namespace from LinkedIn's ``POST#DAY%02d`` (linkedin/parser.py): the
    same day number now identifies two independent publications, one per
    platform, and they must be claimed and tracked separately — publishing
    day16 to Threads must not read as "day16 already published" for LinkedIn,
    or the reverse.
    """
    return "THREADS#DAY%02d" % day


@dataclass(frozen=True)
class ThreadsPost:
    """One day's Threads derivative, as read from the source file."""

    day: int
    title: str
    body: str

    @property
    def key(self) -> str:
        """Stable identifier used as the DynamoDB partition key."""
        return threads_state_key(self.day)


def parse(text: str) -> ThreadsPost:
    """Turn the raw file contents into a :class:`ThreadsPost`.

    Raises:
        ShortsFormatError: if the heading or the Threads section is missing.
    """
    heading = _HEADING.search(text)
    if heading is None:
        raise ShortsFormatError("no '# ■ Day<N> <title>' heading found")

    sections = _split_sections(text)
    if THREADS_SECTION not in sections:
        raise ShortsFormatError(f"missing '## {THREADS_SECTION}' section")

    body = sections[THREADS_SECTION].strip()
    if not body:
        raise ShortsFormatError(f"'## {THREADS_SECTION}' section is empty")

    return ThreadsPost(day=int(heading.group(1)), title=heading.group(2).strip(), body=body)


def _split_sections(text: str) -> dict[str, str]:
    """Map each ``## heading`` to the text that follows it."""
    matches = list(_SECTION.finditer(text))
    sections: dict[str, str] = {}
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections[match.group(1)] = text[match.end() : end]
    return sections
