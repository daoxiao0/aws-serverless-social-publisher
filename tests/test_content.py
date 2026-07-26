import pytest

from publisher.content import ContentStore, day_number


class FakeS3:
    def __init__(self, keys, bodies=None):
        self._keys = keys
        self._bodies = bodies or {}

    def get_paginator(self, _name):
        keys = self._keys

        class Paginator:
            def paginate(self, **_kwargs):
                yield {"Contents": [{"Key": k} for k in keys]}

        return Paginator()

    def get_object(self, Bucket, Key):  # noqa: N803 - boto3 argument casing
        class Body:
            def read(inner):
                return self._bodies[Key].encode("utf-8")

        return {"Body": Body()}


def test_posts_are_ordered_by_day_number_not_lexically():
    # "day10" sorts before "day9" as a string; the backlog must not publish
    # out of order because of that.
    store = ContentStore(FakeS3(["p/day10_b.md", "p/day9_a.md", "p/day2_c.md"]), "bucket", "p/")
    assert store.list_posts() == ["p/day2_c.md", "p/day9_a.md", "p/day10_b.md"]


def test_non_markdown_and_unnumbered_files_are_ignored():
    store = ContentStore(FakeS3(["p/day1_a.md", "p/README.md", "p/day2_b.txt"]), "bucket")
    assert store.list_posts() == ["p/day1_a.md"]


def test_read_decodes_utf8():
    store = ContentStore(FakeS3(["p/day1.md"], {"p/day1.md": "本文"}), "bucket")
    assert store.read("p/day1.md") == "本文"


def test_day_number_extracts_the_digits():
    assert day_number("posts/day07_title.md") == 7


def test_day_number_rejects_a_key_without_one():
    with pytest.raises(ValueError, match="no day number"):
        day_number("posts/README.md")
