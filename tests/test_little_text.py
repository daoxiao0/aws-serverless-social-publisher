"""LinkedIn's commentary field is little text, not plain text.

An unescaped reserved character does not produce an error. The API returns
201 Created and silently drops everything from that character onwards, which
is how this went unnoticed until a published post was read by a human.
"""

import json

import pytest

from publisher.linkedin.client import LinkedInClient, Response, escape_little_text


class Recorder:
    def __init__(self):
        self.body = None

    def __call__(self, method, url, headers, body):
        self.body = json.loads(body) if body else None
        return Response(201, {"x-restli-id": "urn:li:share:1"}, "")


def test_parenthesis_is_escaped():
    # The character that truncated day13 in production.
    assert escape_little_text("OAC (Origin Access Control)") == r"OAC \(Origin Access Control\)"


@pytest.mark.parametrize("char", list("|{}@[]()<>*_~"))
def test_every_reserved_character_is_escaped(char):
    assert escape_little_text("a%sb" % char) == "a\\%sb" % char


def test_backslash_is_escaped():
    assert escape_little_text(r"path\to") == r"path\\to"


def test_hashtags_survive():
    # Escaping '#' would turn hashtags into literal text and lose the reach.
    assert escape_little_text("#AWS #S3") == "#AWS #S3"


def test_japanese_hashtags_survive():
    assert escape_little_text("#クラウド") == "#クラウド"


def test_lone_hash_is_escaped():
    assert escape_little_text("issue # 5") == r"issue \# 5"


def test_trailing_hash_is_escaped():
    # Not a hashtag, so it is escaped and LinkedIn renders it literally.
    assert escape_little_text("C#") == r"C\#"
    assert escape_little_text("ends with #") == "ends with \\#"


def test_ordinary_text_is_untouched():
    text = "「ReactアプリをAWSで公開したい」──S3+CloudFrontが最もコスパの良い構成です。"
    assert escape_little_text(text) == text


def test_create_post_escapes_before_sending():
    recorder = Recorder()
    client = LinkedInClient("t", transport=recorder)
    client.create_post("補足：\n- OAC (Origin Access Control)", author="urn:li:person:x")
    assert recorder.body["commentary"] == "補足：\n- OAC \\(Origin Access Control\\)"


def test_create_comment_escapes_before_sending():
    recorder = Recorder()
    client = LinkedInClient("t", transport=recorder)
    client.create_comment("urn:li:share:1", "see (this)", author="urn:li:person:x")
    assert recorder.body["message"]["text"] == "see \\(this\\)"
