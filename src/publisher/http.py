"""Minimal HTTP transport shared by every platform client.

Extracted from ``linkedin.py`` once a second platform (Threads) needed the
same request/response shape. Both clients inject a :data:`Transport` so their
tests never touch the network.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from typing import Callable, NamedTuple


class Response(NamedTuple):
    status: int
    headers: dict
    body: str


Transport = Callable[[str, str, dict, bytes | None], Response]


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
