import pytest

from publisher.parser import Post, PostFormatError, parse

SAMPLE = """# ■ Day13 S3静的ホスティング

## 投稿本文

「ReactアプリをAWSで公開したい」──S3+CloudFrontが最もコスパの良い構成です。

───

"I want to put my React app on AWS." S3 + CloudFront is the answer.

#AWS #S3 #CloudFront

---

## コメント
補足（用語メモ）

- **静的ウェブサイトホスティング** (Static Website Hosting)
  S3バケットをWebサーバーとして公開する機能
"""


def test_parses_day_and_title():
    post = parse(SAMPLE)
    assert post.day == 13
    assert post.title == "S3静的ホスティング"


def test_body_keeps_both_languages_and_hashtags():
    body = parse(SAMPLE).body
    assert "ReactアプリをAWSで公開したい" in body
    assert "S3 + CloudFront is the answer." in body
    assert body.endswith("#AWS #S3 #CloudFront")


def test_body_drops_the_horizontal_rule_before_the_glossary():
    # The '---' separator is layout in the source file, not content.
    assert "---" not in parse(SAMPLE).body


def test_glossary_is_captured_separately():
    glossary = parse(SAMPLE).glossary
    assert glossary.startswith("補足（用語メモ）")
    assert "Static Website Hosting" in glossary


def test_key_is_zero_padded():
    assert parse(SAMPLE).key == "POST#DAY13"
    assert Post(day=7, title="x", body="y", glossary="").key == "POST#DAY07"


def test_missing_heading_is_rejected():
    with pytest.raises(PostFormatError, match="heading"):
        parse("## 投稿本文\n\nbody\n")


def test_missing_body_section_is_rejected():
    with pytest.raises(PostFormatError, match="投稿本文"):
        parse("# ■ Day13 title\n\n## コメント\nnotes\n")


def test_empty_body_section_is_rejected():
    with pytest.raises(PostFormatError, match="empty"):
        parse("# ■ Day13 title\n\n## 投稿本文\n\n\n## コメント\nnotes\n")


def test_glossary_is_optional():
    post = parse("# ■ Day13 title\n\n## 投稿本文\n\nbody text\n")
    assert post.glossary == ""
