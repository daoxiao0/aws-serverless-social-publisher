"""Parse a source post file into its publishable parts.

Source files live in the content repository and look like this::

    # ■ Day13 S3静的ホスティング

    ## 投稿本文

    ...Japanese body...
    ───
    ...English body...

    #AWS #S3

    ---

    ## コメント
    補足（用語メモ）

    - **用語** (Term)
      one-line description

The two sections stay separate in the source even though they are published
as a single post today. See docs/adr/0003-glossary-inline.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_HEADING = re.compile(r"^#[ \t]*■[ \t]*Day(\d+)[ \t]+(.+?)[ \t]*$", re.MULTILINE)
_SECTION = re.compile(r"^##[ \t]+(.+?)[ \t]*$", re.MULTILINE)
_TRAILING_RULE = re.compile(r"\n-{3,}\s*$")

BODY_SECTION = "投稿本文"
GLOSSARY_SECTION = "コメント"


class PostFormatError(ValueError):
    """The source file does not match the expected structure."""


@dataclass(frozen=True)
class Post:
    """One day's post, as read from the source file."""

    day: int
    title: str
    body: str
    glossary: str

    @property
    def key(self) -> str:
        """Stable identifier used as the DynamoDB partition key."""
        return f"POST#DAY{self.day:02d}"


def parse(text: str) -> Post:
    """Turn the raw file contents into a :class:`Post`.

    Raises:
        PostFormatError: if the heading or the body section is missing.
    """
    heading = _HEADING.search(text)
    if heading is None:
        raise PostFormatError("no '# ■ Day<N> <title>' heading found")

    sections = _split_sections(text)
    if BODY_SECTION not in sections:
        raise PostFormatError(f"missing '## {BODY_SECTION}' section")

    body = _TRAILING_RULE.sub("", sections[BODY_SECTION]).strip()
    if not body:
        raise PostFormatError(f"'## {BODY_SECTION}' section is empty")

    return Post(
        day=int(heading.group(1)),
        title=heading.group(2).strip(),
        body=body,
        glossary=sections.get(GLOSSARY_SECTION, "").strip(),
    )


def _split_sections(text: str) -> dict[str, str]:
    """Map each ``## heading`` to the text that follows it."""
    matches = list(_SECTION.finditer(text))
    sections: dict[str, str] = {}
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections[match.group(1)] = text[match.end() : end]
    return sections
