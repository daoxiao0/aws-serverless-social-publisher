"""A minimal Threads (Meta Graph API) client for publishing text posts.

Threads splits publishing into two calls — create a container, then publish
it by its ``creation_id`` — a shape designed for media that takes time to
process. Text-only posts do not need the extra round trip, but the API does
not offer a shortcut, so both calls happen every time.

Unlike LinkedIn (see ``linkedin.py``), Threads issues a refresh token: a
long-lived token is valid 60 days and can be exchanged for a new 60-day token
at any point after the first 24 hours. See ADR-0007 for why that changes how
this client's expiry handling differs from LinkedIn's.
"""

from __future__ import annotations

import json
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .http import Response, Transport, urllib_transport  # re-exported for callers and tests

GRAPH_BASE = "https://graph.threads.net/v1.0"

#: A refreshed token is valid for another 60 days. Meta does not return an
#: absolute expiry, only ``expires_in`` seconds, so this is computed at the
#: call site from ``datetime.now()`` — see refresh_token().
REFRESH_LIFETIME = timedelta(seconds=60 * 24 * 3600)


class ThreadsError(RuntimeError):
    """A Threads API call failed."""

    def __init__(self, message: str, status: int = 0, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body


class TokenExpiredError(ThreadsError):
    """The access token is no longer valid and refreshing it did not help.

    Unlike LinkedIn's version of this error, this one is reachable only after
    a refresh attempt has already failed — see refresh_if_needed() in
    threads_handler.py. Retrying the post itself is still pointless.
    """


class PermissionDeniedError(ThreadsError):
    """The token is valid but lacks the permission for this call."""


class RateLimitedError(ThreadsError):
    """Too many requests."""


@dataclass(frozen=True)
class RefreshedToken:
    """The result of exchanging one long-lived token for another."""

    access_token: str
    expires_at: datetime


def refresh_token(
    access_token: str,
    *,
    graph_base: str = GRAPH_BASE,
    transport: Transport = None,  # type: ignore[assignment]
) -> RefreshedToken:
    """Exchange a long-lived token for a fresh 60-day one.

    Meta allows this any time after the token is 24 hours old, and it does
    not invalidate the token being refreshed. Called on a schedule (see
    threads_handler.py) rather than only on failure, so the token in Secrets
    Manager rarely gets close to expiry at all.
    """
    transport = transport or urllib_transport
    query = urllib.parse.urlencode(
        {"grant_type": "th_refresh_token", "access_token": access_token}
    )
    response = transport("GET", f"{graph_base}/refresh_access_token?{query}", {}, None)
    if response.status >= 300:
        raise _error_for("GET", "/refresh_access_token", response)

    payload = json.loads(response.body)
    expires_in = payload.get("expires_in", REFRESH_LIFETIME.total_seconds())
    return RefreshedToken(
        access_token=payload["access_token"],
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=expires_in),
    )


class ThreadsClient:
    """Publishes text posts as the user who authorized the access token."""

    def __init__(
        self,
        access_token: str,
        user_id: str,
        *,
        graph_base: str = GRAPH_BASE,
        transport: Transport = urllib_transport,
    ):
        self._token = access_token
        self._user_id = user_id
        self._base = graph_base.rstrip("/")
        self._transport = transport

    def create_post(self, text: str) -> str:
        """Publish `text` and return the id of the created post."""
        creation_id = self._create(media_type="TEXT", text=text)
        return self._publish(creation_id)

    # -- internals ------------------------------------------------------

    def _create(self, **params) -> str:
        response = self._request("POST", f"/{self._user_id}/threads", params)
        return json.loads(response.body)["id"]

    def _publish(self, creation_id: str) -> str:
        response = self._request(
            "POST", f"/{self._user_id}/threads_publish", {"creation_id": creation_id}
        )
        return json.loads(response.body)["id"]

    def _request(self, method: str, path: str, params: dict) -> Response:
        query = urllib.parse.urlencode({**params, "access_token": self._token})
        response = self._transport(method, f"{self._base}{path}?{query}", {}, None)
        if response.status >= 300:
            raise _error_for(method, path, response)
        return response


def _error_for(method: str, path: str, response: Response) -> ThreadsError:
    summary = "%s %s returned %d" % (method, path, response.status)

    error_type = ""
    try:
        error_type = json.loads(response.body).get("error", {}).get("type", "")
    except (json.JSONDecodeError, AttributeError):
        pass  # Not every failure response is JSON — a 5xx may be plain text.

    # Threads reports an expired or invalid token as a 400 with this type,
    # not as a 401 the way LinkedIn does.
    if error_type == "OAuthException":
        return TokenExpiredError(summary, response.status, response.body)
    if response.status == 403:
        return PermissionDeniedError(summary, response.status, response.body)
    if response.status == 429:
        return RateLimitedError(summary, response.status, response.body)
    return ThreadsError(summary, response.status, response.body)
