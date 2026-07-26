import json
from datetime import datetime, timedelta, timezone

import pytest

from publisher.linkedin import LinkedInError, Response, TokenInfo, introspect


def transport_returning(status=200, payload=None, recorder=None):
    def transport(method, url, headers, body):
        if recorder is not None:
            recorder.update({"method": method, "url": url, "headers": headers, "body": body})
        return Response(status, {}, json.dumps(payload or {}))

    return transport


def epoch(days_from_now):
    return int((datetime.now(timezone.utc) + timedelta(days=days_from_now)).timestamp())


def test_posts_form_encoded_credentials_to_the_oauth_host():
    seen = {}
    introspect("tok", "cid", "sec", transport=transport_returning(recorder=seen))
    assert seen["url"] == "https://www.linkedin.com/oauth/v2/introspectToken"
    assert seen["headers"]["Content-Type"] == "application/x-www-form-urlencoded"
    # Form encoded, not JSON: the OAuth host rejects a JSON body.
    assert b"client_id=cid" in seen["body"]
    assert b"token=tok" in seen["body"]


def test_reads_expiry_status_and_scopes():
    info = introspect(
        "tok", "cid", "sec",
        transport=transport_returning(payload={
            "active": True,
            "status": "active",
            "expires_at": epoch(30),
            "scope": "openid,profile,w_member_social",
        }),
    )
    assert info.active is True
    assert info.status == "active"
    assert info.grants("w_member_social")
    assert 29.9 < info.days_remaining < 30.1


def test_revoked_token_is_reported_as_inactive():
    # Expiry is not the only failure mode; LinkedIn can revoke early.
    info = introspect(
        "tok", "cid", "sec",
        transport=transport_returning(payload={"active": False, "status": "revoked"}),
    )
    assert info.active is False
    assert info.status == "revoked"


def test_scope_string_with_spaces_is_parsed():
    info = introspect(
        "tok", "cid", "sec",
        transport=transport_returning(payload={"active": True, "scope": "openid, w_member_social"}),
    )
    assert info.scopes == frozenset({"openid", "w_member_social"})


def test_missing_expiry_leaves_days_remaining_unknown():
    info = introspect("tok", "cid", "sec", transport=transport_returning(payload={"active": True}))
    assert info.expires_at is None
    assert info.days_remaining is None


@pytest.mark.parametrize("status", [400, 401, 500])
def test_non_200_is_an_error(status):
    with pytest.raises(LinkedInError, match="introspection"):
        introspect("tok", "cid", "sec", transport=transport_returning(status=status))


def test_days_remaining_goes_negative_after_expiry():
    info = TokenInfo(
        active=False,
        status="expired",
        expires_at=datetime.now(timezone.utc) - timedelta(days=3),
        scopes=frozenset(),
    )
    assert info.days_remaining < 0
