import pytest

from publisher.threads.parser import ShortsFormatError, ThreadsPost, parse, threads_state_key

SAMPLE = """# ■ Day16 Lambda環境変数（派生元: posts/day16_Lambda環境変数.md）

## Threads（日本語）

「DBのパスワードをLambdaのコードに直書きしている」——これ、地味に多い落とし穴です。

みなさんは、シークレット情報の管理どうしていますか。

## X（English）

Hardcoding a DB password in your Lambda function? Move it to an environment variable now.

#AWS #Lambda

## Shorts台本（日本語）

DBのパスワードってLambdaのコードに直接書いてませんか？

## Shorts Script（English）

Is your database password sitting right there in your Lambda code?
"""


def test_parses_day_and_title():
    post = parse(SAMPLE)
    assert post.day == 16
    assert post.title == "Lambda環境変数（派生元: posts/day16_Lambda環境変数.md）"


def test_body_is_the_threads_section_only():
    body = parse(SAMPLE).body
    assert "地味に多い落とし穴です" in body
    assert "シークレット情報の管理どうしていますか" in body
    # Nothing from the sections that follow leaks in.
    assert "Hardcoding a DB password" not in body
    assert "Shorts台本" not in body


def test_key_is_the_threads_namespace_zero_padded():
    assert parse(SAMPLE).key == "THREADS#DAY16"
    assert ThreadsPost(day=7, title="x", body="y").key == "THREADS#DAY07"


def test_threads_state_key_is_distinct_from_linkedins():
    # Same day, different platform: must not collide with parser.py's
    # POST#DAY07, or publishing to one platform would look like publishing
    # to both.
    assert threads_state_key(7) == "THREADS#DAY07"


def test_missing_heading_is_rejected():
    with pytest.raises(ShortsFormatError, match="heading"):
        parse("## Threads（日本語）\n\nbody\n")


def test_missing_threads_section_is_rejected():
    with pytest.raises(ShortsFormatError, match="Threads"):
        parse("# ■ Day16 title\n\n## X（English）\nbody\n")


def test_empty_threads_section_is_rejected():
    with pytest.raises(ShortsFormatError, match="empty"):
        parse("# ■ Day16 title\n\n## Threads（日本語）\n\n\n## X（English）\nbody\n")
