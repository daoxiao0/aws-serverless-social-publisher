"""Turn a parsed post into the exact text LinkedIn will receive.

Two things happen here that are easy to overlook:

1. Markdown emphasis is stripped. LinkedIn does not render Markdown, so
   ``**Task Definition**`` would be published with the asterisks visible.
2. The glossary is appended to the body, because creating a comment through
   the API requires partner-only permissions. See
   docs/adr/0003-glossary-inline.md.
"""

from __future__ import annotations

import re

from .parser import Post

#: LinkedIn rejects post text longer than this.
MAX_LENGTH = 3000

_BOLD = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_ITALIC = re.compile(r"(?<!\*)\*(?!\s)([^*\n]+?)(?<!\s)\*(?!\*)")
_GLOSSARY_HEADER = re.compile(r"^補足（用語メモ）[ \t]*$", re.MULTILINE)

GLOSSARY_LEAD = "補足："


class PostTooLongError(ValueError):
    """Rendered text exceeds what LinkedIn accepts."""


def render(post: Post, *, inline_glossary: bool = True) -> str:
    """Render `post` as a single block of plain text.

    Args:
        post: the parsed source post.
        inline_glossary: append the glossary to the body. Set to ``False``
            once the comment API becomes available, so the glossary can be
            posted separately again.

    Raises:
        PostTooLongError: if the result would be rejected by LinkedIn.
    """
    parts = [strip_markdown(post.body)]
    if inline_glossary and post.glossary:
        parts.append(f"{GLOSSARY_LEAD}\n{render_glossary(post)}")

    text = "\n\n".join(parts)
    if len(text) > MAX_LENGTH:
        raise PostTooLongError(
            f"{post.key} renders to {len(text)} characters (limit {MAX_LENGTH})"
        )
    return text


def render_glossary(post: Post) -> str:
    """Render the glossary on its own, for use as a comment or a reminder."""
    without_header = _GLOSSARY_HEADER.sub("", post.glossary)
    return strip_markdown(without_header).strip()


def strip_markdown(text: str) -> str:
    """Remove emphasis markers that LinkedIn would otherwise show literally."""
    return _ITALIC.sub(r"\1", _BOLD.sub(r"\1", text))
