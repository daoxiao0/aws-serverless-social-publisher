"""A minimal LinkedIn client for publishing on behalf of a member.

Only the calls this project needs, using the versioned ``/rest`` API rather
than the deprecated ``/v2/ugcPosts`` endpoint that most tutorials still show.

The HTTP layer is injectable so the tests never touch the network.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, NamedTuple

API_BASE = "https://api.linkedin.com"

#: Token introspection lives on the sign-in host, not the API host, and
#: authenticates with client credentials rather than a bearer token.
OAUTH_BASE = "https://www.linkedin.com"

#: LinkedIn versions its API by month. Bump deliberately, not automatically:
#: a version LinkedIn has sunset returns 400 on every call.
API_VERSION = "202607"


class Response(NamedTuple):
    status: int
    headers: dict
    body: str


Transport = Callable[[str, str, dict, bytes | None], Response]


class LinkedInError(RuntimeError):
    """A LinkedIn API call failed."""

    def __init__(self, message: str, status: int = 0, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body


class TokenExpiredError(LinkedInError):
    """The access token is no longer valid.

    Never retry this. A self-serve app has no refresh token, so every retry
    produces another 401 while the real fix is a human re-authorizing.
    See docs/adr/0004-access-token-lifecycle.md.
    """


class PermissionDeniedError(LinkedInError):
    """The token is valid but lacks the permission for this call."""


class RateLimitedError(LinkedInError):
    """Too many requests. The member limit is 150 per day."""


def urllib_transport(method: str, url: str, headers: dict, body: bytes | None) -> Response:
    """Default transport, built on the standard library."""
    request = urllib.request.Request(url, data=body, method=method)
    for name, value in headers.items():
        request.add_header(name, value)
    try:
        with urllib.request.urlopen(request) as response:
            return Response(response.status, dict(response.headers), response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as error:
        return Response(error.code, dict(error.headers), error.read().decode("utf-8", "replace"))


@dataclass(frozen=True)
class TokenInfo:
    """What LinkedIn says about an access token."""

    active: bool
    status: str
    expires_at: datetime | None
    scopes: frozenset[str]

    @property
    def days_remaining(self) -> float | None:
        if self.expires_at is None:
            return None
        return (self.expires_at - datetime.now(timezone.utc)).total_seconds() / 86400

    def grants(self, scope: str) -> bool:
        return scope in self.scopes


def introspect(
    access_token: str,
    client_id: str,
    client_secret: str,
    *,
    oauth_base: str = OAUTH_BASE,
    transport: Transport = None,  # type: ignore[assignment]
) -> TokenInfo:
    """Ask LinkedIn when this token expires, instead of assuming.

    The alternative is recording the expiry by hand at authorization time,
    which is wrong the moment somebody re-authorizes and forgets to update it
    — exactly the silent failure the expiry alarm exists to prevent.

    Also reports ``revoked``. LinkedIn reserves the right to revoke tokens
    early, so "not expired yet" is not the same as "usable".
    """
    transport = transport or urllib_transport
    body = urllib.parse.urlencode(
        {"client_id": client_id, "client_secret": client_secret, "token": access_token}
    ).encode()
    response = transport(
        "POST",
        oauth_base.rstrip("/") + "/oauth/v2/introspectToken",
        {"Content-Type": "application/x-www-form-urlencoded"},
        body,
    )
    if response.status != 200:
        # 400 is a bad client id or token, 401 a bad client secret. Neither is
        # worth distinguishing at the call site: both mean "fix the secret".
        raise LinkedInError(
            "token introspection returned %d" % response.status,
            response.status,
            response.body,
        )

    payload = json.loads(response.body)
    expires_at = payload.get("expires_at")
    return TokenInfo(
        active=bool(payload.get("active")),
        status=payload.get("status", "unknown"),
        expires_at=datetime.fromtimestamp(expires_at, timezone.utc) if expires_at else None,
        scopes=frozenset(s.strip() for s in payload.get("scope", "").split(",") if s.strip()),
    )


class LinkedInClient:
    """Publishes posts as the member who authorized the access token."""

    def __init__(
        self,
        access_token: str,
        *,
        version: str = API_VERSION,
        api_base: str = API_BASE,
        transport: Transport = urllib_transport,
    ):
        self._token = access_token
        self._version = version
        self._base = api_base.rstrip("/")
        self._transport = transport
        self._person_urn: str | None = None

    # -- public API ---------------------------------------------------------

    def person_urn(self) -> str:
        """The URN of the authorizing member, used as the post author.

        Requires the ``openid`` and ``profile`` scopes, which come from the
        Sign In with LinkedIn using OpenID Connect product. Without them a
        token can create posts in principle but has no value for ``author``.
        """
        if self._person_urn is None:
            payload = self._request("GET", "/v2/userinfo", versioned=False)
            self._person_urn = "urn:li:person:" + json.loads(payload.body)["sub"]
        return self._person_urn

    def create_post(self, text: str, *, author: str | None = None, visibility: str = "PUBLIC") -> str:
        """Publish `text` and return the URN of the created post."""
        response = self._request(
            "POST",
            "/rest/posts",
            body={
                "author": author or self.person_urn(),
                "commentary": text,
                "visibility": visibility,
                "distribution": {
                    "feedDistribution": "MAIN_FEED",
                    "targetEntities": [],
                    "thirdPartyDistributionChannels": [],
                },
                "lifecycleState": "PUBLISHED",
                "isReshareDisabledByAuthor": False,
            },
        )
        urn = response.headers.get("x-restli-id")
        if not urn:
            raise LinkedInError(
                "post was created but the response carried no x-restli-id header",
                response.status,
                response.body,
            )
        return urn

    def delete_post(self, urn: str) -> None:
        self._request("DELETE", "/rest/posts/" + urllib.parse.quote(urn, safe=""))

    def create_comment(self, post_urn: str, text: str, *, author: str | None = None) -> str:
        """Comment on a post.

        Raises :class:`PermissionDeniedError` on the self-serve tier: this
        endpoint needs ``w_member_social_feed`` from the Community Management
        API. Kept so that the capability can be switched on the day access is
        granted, and so scripts/check_access.py can probe for it.
        """
        response = self._request(
            "POST",
            "/rest/socialActions/%s/comments" % urllib.parse.quote(post_urn, safe=""),
            body={
                "actor": author or self.person_urn(),
                "object": post_urn,
                "message": {"text": text},
            },
        )
        return response.headers.get("x-restli-id", "")

    # -- internals ----------------------------------------------------------

    def _request(self, method: str, path: str, *, body: dict | None = None, versioned: bool = True) -> Response:
        headers = {
            "Authorization": "Bearer " + self._token,
            "X-Restli-Protocol-Version": "2.0.0",
        }
        if versioned:
            headers["LinkedIn-Version"] = self._version
        payload = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            payload = json.dumps(body).encode()

        response = self._transport(method, self._base + path, headers, payload)
        if response.status >= 300:
            raise self._error_for(method, path, response)
        return response

    @staticmethod
    def _error_for(method: str, path: str, response: Response) -> LinkedInError:
        summary = "%s %s returned %d" % (method, path, response.status)
        if response.status == 401:
            return TokenExpiredError(summary, response.status, response.body)
        if response.status == 403:
            return PermissionDeniedError(summary, response.status, response.body)
        if response.status == 429:
            return RateLimitedError(summary, response.status, response.body)
        return LinkedInError(summary, response.status, response.body)
