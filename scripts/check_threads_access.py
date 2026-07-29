#!/usr/bin/env python3
"""Check what a Threads access token is actually allowed to do.

Verifies the two things this project depends on against the live API:

    1. can we resolve the account's identity?
    2. can the token be refreshed?

Unlike check_access.py (LinkedIn), this does not create a real test post.
The Threads Graph API has no documented way to delete a post once created —
LinkedIn's script can post-then-delete safely because DELETE /rest/posts
exists; Threads offers no equivalent, so a real test post here would be
permanent. Whether posting itself works is verified the first time the
Lambda runs with DRY_RUN unset — see docs/setup-threads-app.md.

The access token is never printed.

Usage:
    python scripts/check_threads_access.py [--token-file PATH] [--user-id-file PATH]
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request

GRAPH = "https://graph.threads.net/v1.0"
DEFAULT_TOKEN_FILE = pathlib.Path.home() / ".threads_token"


def call(method, url):
    """Make one API call. Returns (status, body_text)."""
    request = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace")


def summarize(status, body, limit=300):
    print("    status: %s" % status)
    body = " ".join(body.split())
    if body:
        print("    body  : %s" % body[:limit])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--token-file", type=pathlib.Path, default=DEFAULT_TOKEN_FILE)
    args = parser.parse_args()

    if not args.token_file.exists():
        print("no token file at %s" % args.token_file)
        print("see docs/setup-threads-app.md")
        return 2

    token = args.token_file.read_text(encoding="utf-8-sig").strip()

    print("[1] identity   GET /me")
    query = urllib.parse.urlencode({"fields": "id,username", "access_token": token})
    status, body = call("GET", f"{GRAPH}/me?{query}")
    if status != 200:
        summarize(status, body)
        print("\ntoken is not usable. If the error type is OAuthException, it has expired.")
        return 1
    identity = json.loads(body)
    print("    ok, user_id=%s username=%s" % (identity["id"], identity.get("username", "?")))
    print("    (this is the value TOKEN_SECRET_ID's user_id field must hold)")

    print("\n[2] refresh    GET /refresh_access_token")
    query = urllib.parse.urlencode({"grant_type": "th_refresh_token", "access_token": token})
    status, body = call("GET", f"{GRAPH}/refresh_access_token?{query}")
    summarize(status, body if status >= 300 else "")
    refreshable = status == 200
    if refreshable:
        expires_in_days = json.loads(body).get("expires_in", 0) / 86400
        print("    ok, new token valid for %.0f more days" % expires_in_days)
        print("    NOTE: this call issued a new token. If you plan to keep using")
        print("    the token in %s, replace it with the refreshed one." % args.token_file)

    print("\n---")
    print("identity : OK")
    print("refresh  : %s" % ("OK" if refreshable else "FAILED"))
    print("posting  : not checked here — see docs/setup-threads-app.md, step 8")
    return 0 if refreshable else 1


if __name__ == "__main__":
    sys.exit(main())
