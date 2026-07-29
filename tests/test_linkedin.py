import json

import pytest

from publisher.linkedin.client import (
    LinkedInClient,
    LinkedInError,
    PermissionDeniedError,
    RateLimitedError,
    Response,
    TokenExpiredError,
)


class FakeTransport:
    """Records requests and replays canned responses."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, headers, body):
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "body": json.loads(body) if body else None,
            }
        )
        return self.responses.pop(0)


def created(urn="urn:li:share:1"):
    return Response(201, {"x-restli-id": urn}, "")


def userinfo(sub="abc123"):
    return Response(200, {}, json.dumps({"sub": sub}))


def test_person_urn_is_built_from_userinfo():
    transport = FakeTransport(userinfo("abc123"))
    client = LinkedInClient("t", transport=transport)
    assert client.person_urn() == "urn:li:person:abc123"


def test_person_urn_is_fetched_once_and_cached():
    transport = FakeTransport(userinfo())
    client = LinkedInClient("t", transport=transport)
    client.person_urn()
    client.person_urn()
    assert len(transport.calls) == 1


def test_userinfo_is_not_sent_with_a_version_header():
    # /v2 endpoints reject the versioned header that /rest requires.
    transport = FakeTransport(userinfo())
    LinkedInClient("t", transport=transport).person_urn()
    assert "LinkedIn-Version" not in transport.calls[0]["headers"]


def test_create_post_returns_the_urn_from_the_response_header():
    transport = FakeTransport(userinfo(), created("urn:li:share:99"))
    client = LinkedInClient("t", transport=transport)
    assert client.create_post("hello") == "urn:li:share:99"


def test_create_post_uses_the_versioned_endpoint():
    transport = FakeTransport(created())
    client = LinkedInClient("t", version="202607", transport=transport)
    client.create_post("hello", author="urn:li:person:x")
    call = transport.calls[0]
    assert call["url"].endswith("/rest/posts")
    assert call["headers"]["LinkedIn-Version"] == "202607"
    assert call["headers"]["Authorization"] == "Bearer t"


def test_create_post_sends_the_expected_body():
    transport = FakeTransport(created())
    client = LinkedInClient("t", transport=transport)
    client.create_post("hello", author="urn:li:person:x", visibility="CONNECTIONS")
    body = transport.calls[0]["body"]
    assert body["author"] == "urn:li:person:x"
    assert body["commentary"] == "hello"
    assert body["visibility"] == "CONNECTIONS"
    assert body["lifecycleState"] == "PUBLISHED"


def test_missing_urn_header_is_an_error():
    transport = FakeTransport(Response(201, {}, ""))
    client = LinkedInClient("t", transport=transport)
    with pytest.raises(LinkedInError, match="x-restli-id"):
        client.create_post("hello", author="urn:li:person:x")


def test_401_raises_token_expired():
    transport = FakeTransport(Response(401, {}, "expired"))
    client = LinkedInClient("t", transport=transport)
    with pytest.raises(TokenExpiredError) as info:
        client.create_post("hello", author="urn:li:person:x")
    assert info.value.status == 401


def test_403_raises_permission_denied():
    # What the comments endpoint returns on the self-serve tier.
    transport = FakeTransport(Response(403, {}, "ACCESS_DENIED"))
    client = LinkedInClient("t", transport=transport)
    with pytest.raises(PermissionDeniedError):
        client.create_comment("urn:li:share:1", "note", author="urn:li:person:x")


def test_429_raises_rate_limited():
    transport = FakeTransport(Response(429, {}, ""))
    client = LinkedInClient("t", transport=transport)
    with pytest.raises(RateLimitedError):
        client.create_post("hello", author="urn:li:person:x")


def test_delete_encodes_the_urn_in_the_path():
    transport = FakeTransport(Response(204, {}, ""))
    client = LinkedInClient("t", transport=transport)
    client.delete_post("urn:li:share:1")
    assert transport.calls[0]["url"].endswith("/rest/posts/urn%3Ali%3Ashare%3A1")
