import pytest

from publisher.threads.parser import ThreadsPost
from publisher.threads.renderer import MAX_LENGTH, PostTooLongError, render, strip_markdown


def make_post(body="body text") -> ThreadsPost:
    return ThreadsPost(day=16, title="title", body=body)


def test_bold_markers_are_removed():
    # Threads shows the asterisks literally, so they must not survive.
    assert strip_markdown("**環境変数**を使いましょう") == "環境変数を使いましょう"


def test_italic_markers_are_removed():
    assert strip_markdown("this is *important* here") == "this is important here"


def test_bare_asterisk_is_left_alone():
    assert strip_markdown("2 * 3 = 6") == "2 * 3 = 6"


def test_render_returns_the_body_unchanged_when_clean():
    assert render(make_post()) == "body text"


def test_too_long_is_rejected():
    with pytest.raises(PostTooLongError, match="THREADS#DAY16"):
        render(make_post(body="あ" * (MAX_LENGTH + 1)))


def test_exactly_at_the_limit_is_accepted():
    assert len(render(make_post(body="あ" * MAX_LENGTH))) == MAX_LENGTH
