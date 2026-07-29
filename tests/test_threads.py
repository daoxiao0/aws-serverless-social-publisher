import json
from datetime import datetime, timezone

import pytest

from publisher.threads.client import (
    PermissionDeniedError,
    RateLimitedError,
    Response,
    ThreadsClient,
    ThreadsError,
    TokenExpiredError,
    refresh_token,
)


class FakeTransport:
    """Records requests and replays canned responses."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, headers, body):
        self.calls.append({"method": method, "url": url, "headers": headers, "body": body})
        return self.responses.pop(0)


def ok(payload):
    return Response(200, {}, json.dumps(payload))


def oauth_error(status=400):
    return Response(
        status,
        {},
        json.dumps({"error": {"message": "Error validating access token", "type": "OAuthException", "code": 190}}),
    )


class TestCreatePost:
    def test_creates_then_publishes(self):
        transport = FakeTransport(ok({"id": "creation-1"}), ok({"id": "post-1"}))
        client = ThreadsClient("tok", "user-9", transport=transport)
        assert client.create_post("hello") == "post-1"
        assert len(transport.calls) == 2

    def test_create_call_shape(self):
        transport = FakeTransport(ok({"id": "c1"}), ok({"id": "p1"}))
        ThreadsClient("tok", "user-9", transport=transport).create_post("hello")
        call = transport.calls[0]
        assert call["method"] == "POST"
        assert call["url"].startswith("https://graph.threads.net/v1.0/user-9/threads?")
        assert "media_type=TEXT" in call["url"]
        assert "text=hello" in call["url"]
        assert "access_token=tok" in call["url"]
        # Threads Graph API takes parameters on the query string; no body.
        assert call["body"] is None

    def test_publish_call_uses_the_creation_id(self):
        transport = FakeTransport(ok({"id": "creation-42"}), ok({"id": "p1"}))
        ThreadsClient("tok", "user-9", transport=transport).create_post("hello")
        call = transport.calls[1]
        assert call["url"].startswith("https://graph.threads.net/v1.0/user-9/threads_publish?")
        assert "creation_id=creation-42" in call["url"]

    def test_oauth_error_raises_token_expired(self):
        transport = FakeTransport(oauth_error())
        client = ThreadsClient("tok", "user-9", transport=transport)
        with pytest.raises(TokenExpiredError) as info:
            client.create_post("hello")
        assert info.value.status == 400

    def test_403_raises_permission_denied(self):
        transport = FakeTransport(Response(403, {}, json.dumps({"error": {"message": "nope"}})))
        client = ThreadsClient("tok", "user-9", transport=transport)
        with pytest.raises(PermissionDeniedError):
            client.create_post("hello")

    def test_429_raises_rate_limited(self):
        transport = FakeTransport(Response(429, {}, json.dumps({"error": {"message": "slow down"}})))
        client = ThreadsClient("tok", "user-9", transport=transport)
        with pytest.raises(RateLimitedError):
            client.create_post("hello")

    def test_other_failure_raises_generic_error(self):
        transport = FakeTransport(Response(500, {}, "internal error"))
        client = ThreadsClient("tok", "user-9", transport=transport)
        with pytest.raises(ThreadsError):
            client.create_post("hello")

    def test_non_json_error_body_does_not_crash_classification(self):
        # A 5xx from an upstream proxy may not be JSON at all.
        transport = FakeTransport(Response(502, {}, "<html>bad gateway</html>"))
        client = ThreadsClient("tok", "user-9", transport=transport)
        with pytest.raises(ThreadsError):
            client.create_post("hello")


class TestRefreshToken:
    def test_returns_the_new_token_and_computed_expiry(self):
        transport = FakeTransport(ok({"access_token": "new-tok", "expires_in": 5184000}))
        refreshed = refresh_token("old-tok", transport=transport)
        assert refreshed.access_token == "new-tok"
        # ~60 days out, allowing for test execution time.
        remaining_days = (refreshed.expires_at - datetime.now(timezone.utc)).total_seconds() / 86400
        assert 59.9 < remaining_days < 60.1

    def test_call_shape(self):
        transport = FakeTransport(ok({"access_token": "new-tok", "expires_in": 5184000}))
        refresh_token("old-tok", transport=transport)
        call = transport.calls[0]
        assert call["method"] == "GET"
        assert call["url"].startswith("https://graph.threads.net/v1.0/refresh_access_token?")
        assert "grant_type=th_refresh_token" in call["url"]
        assert "access_token=old-tok" in call["url"]

    def test_failed_refresh_raises_token_expired(self):
        transport = FakeTransport(oauth_error())
        with pytest.raises(TokenExpiredError):
            refresh_token("dead-tok", transport=transport)
