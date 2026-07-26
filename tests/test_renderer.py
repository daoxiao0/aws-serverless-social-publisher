import pytest

from publisher.parser import Post
from publisher.renderer import (
    MAX_LENGTH,
    PostTooLongError,
    render,
    render_glossary,
    strip_markdown,
)


def make_post(body="body text", glossary="") -> Post:
    return Post(day=13, title="title", body=body, glossary=glossary)


def test_bold_markers_are_removed():
    # LinkedIn shows the asterisks literally, so they must not survive.
    assert strip_markdown("**タスク定義**はコンテナの設計図") == "タスク定義はコンテナの設計図"


def test_italic_markers_are_removed():
    assert strip_markdown("this is *important* here") == "this is important here"


def test_bare_asterisk_is_left_alone():
    assert strip_markdown("2 * 3 = 6") == "2 * 3 = 6"


def test_glossary_is_appended_to_the_body():
    post = make_post(glossary="補足（用語メモ）\n\n- **GSI** (Global Secondary Index)\n  an index")
    text = render(post)
    assert text.startswith("body text")
    assert "補足：" in text
    assert "GSI (Global Secondary Index)" in text
    # The source header is replaced by the lead-in, not duplicated.
    assert "用語メモ" not in text


def test_glossary_can_be_left_out():
    post = make_post(glossary="補足（用語メモ）\n\n- **GSI** (x)\n  y")
    assert render(post, inline_glossary=False) == "body text"


def test_empty_glossary_adds_nothing():
    assert render(make_post()) == "body text"


def test_render_glossary_alone_drops_the_header():
    post = make_post(glossary="補足（用語メモ）\n\n- **GSI** (x)\n  an index")
    assert render_glossary(post) == "- GSI (x)\n  an index"


def test_too_long_is_rejected():
    with pytest.raises(PostTooLongError, match="POST#DAY13"):
        render(make_post(body="あ" * (MAX_LENGTH + 1)))


def test_exactly_at_the_limit_is_accepted():
    assert len(render(make_post(body="あ" * MAX_LENGTH))) == MAX_LENGTH
