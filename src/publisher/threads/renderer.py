"""Turn a parsed Threads post into the exact text Threads will receive.

/aws-shorts is instructed not to use Markdown emphasis in the Threads
section, because Threads displays asterisks literally rather than rendering
them — the same failure LinkedIn's renderer strips defensively (linkedin/renderer.py).
This does the same, on the chance a future edit slips one in anyway.
"""

from __future__ import annotations

import re

from .parser import ThreadsPost

#: Threads rejects text past this length. Measured, not documented: past this
#: point the API returns a bare HTTP 500 with no length-specific message,
#: which reads exactly like a transient outage unless you already know to
#: check the character count first (content repository,
#: Content-Dharma-Flow.md, 2026-07-28 incident).
MAX_LENGTH = 500

_BOLD = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_ITALIC = re.compile(r"(?<!\*)\*(?!\s)([^*\n]+?)(?<!\s)\*(?!\*)")


class PostTooLongError(ValueError):
    """Rendered text exceeds what Threads accepts."""


def render(post: ThreadsPost) -> str:
    """Render `post` as the plain text Threads should receive.

    Raises:
        PostTooLongError: if the result would be rejected by Threads.
    """
    text = strip_markdown(post.body)
    if len(text) > MAX_LENGTH:
        raise PostTooLongError(
            f"{post.key} renders to {len(text)} characters (limit {MAX_LENGTH})"
        )
    return text


def strip_markdown(text: str) -> str:
    """Remove emphasis markers that Threads would otherwise show literally."""
    return _ITALIC.sub(r"\1", _BOLD.sub(r"\1", text))
