#!/usr/bin/env python3
"""Check what a LinkedIn access token is actually allowed to do.

Third-party documentation about LinkedIn permissions is unreliable, so this
verifies the two things this project depends on against the live API:

    1. can we create a post?
    2. can we comment on it?

To test the second one honestly there has to be a post to comment on. This
script creates one visible to connections only, then deletes it. The window is
a couple of seconds, but it is a real post on your real profile, so the script
asks before doing it.

The access token is never printed.

Usage:
    python scripts/check_access.py [--token-file PATH] [--yes]
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.linkedin.com"
VERSIONS = ["202607", "202606", "202601", "202401"]
DEFAULT_TOKEN_FILE = pathlib.Path.home() / ".linkedin_token"


def call(token, method, path, body=None, version=None):
    """Make one API call. Returns (status, headers, body_text)."""
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(API + path, data=data, method=method)
    request.add_header("Authorization", "Bearer " + token)
    request.add_header("X-Restli-Protocol-Version", "2.0.0")
    if version:
        request.add_header("LinkedIn-Version", version)
    if data:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, dict(response.headers), response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read().decode("utf-8", "replace")


def summarize(status, body, limit=300):
    print("    status: %s" % status)
    body = " ".join(body.split())
    if body:
        print("    body  : %s" % body[:limit])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--token-file", type=pathlib.Path, default=DEFAULT_TOKEN_FILE)
    parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    args = parser.parse_args()

    if not args.token_file.exists():
        print("no token file at %s" % args.token_file)
        print("see docs/setup-linkedin-app.md")
        return 2

    # utf-8-sig: PowerShell's Set-Content writes a BOM by default on Windows.
    token = args.token_file.read_text(encoding="utf-8-sig").strip()

    print("[1] identity   GET /v2/userinfo")
    status, _, body = call(token, "GET", "/v2/userinfo")
    if status != 200:
        summarize(status, body)
        print("\ntoken is not usable. If this is 401, it has expired.")
        return 1
    sub = json.loads(body)["sub"]
    person = "urn:li:person:" + sub
    print("    ok, person urn resolved (%s...%s)" % (sub[:3], sub[-2:]))

    if not args.yes:
        print("\nThe next step publishes a real post on your profile, visible to")
        print("connections only, and deletes it immediately afterwards.")
        if input("Continue? [y/N] ").strip().lower() not in ("y", "yes"):
            print("stopped, nothing was posted")
            return 0

    print("\n[2] create     POST /rest/posts")
    post = {
        "author": person,
        "commentary": "API connectivity test. This post will be deleted immediately.",
        "visibility": "CONNECTIONS",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": [],
        },
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }
    urn = version_used = None
    for version in VERSIONS:
        status, headers, body = call(token, "POST", "/rest/posts", post, version=version)
        if status in (200, 201):
            urn = headers.get("x-restli-id")
            version_used = version
            print("    ok, created with LinkedIn-Version %s" % version)
            break
        print("    version %s:" % version)
        summarize(status, body)
    if not urn:
        print("\ncannot create posts. Check that the Share on LinkedIn product is")
        print("added AND that the token was generated after adding it.")
        return 1

    print("\n[3] comment    POST /rest/socialActions/{urn}/comments")
    target = urllib.parse.quote(urn, safe="")
    status, _, body = call(
        token,
        "POST",
        "/rest/socialActions/%s/comments" % target,
        {"actor": person, "object": urn, "message": {"text": "API connectivity test."}},
        version=version_used,
    )
    summarize(status, body, limit=400)
    can_comment = status in (200, 201)

    print("\n[4] cleanup    DELETE /rest/posts/{urn}")
    status, _, body = call(token, "DELETE", "/rest/posts/%s" % target, version=version_used)
    summarize(status, body if status >= 300 else "")
    if status >= 300:
        print("    WARNING: the test post was not deleted. Remove it manually:")
        print("    %s" % urn)

    print("\n---")
    print("post   : OK (LinkedIn-Version %s)" % version_used)
    print("comment: %s" % ("OK" if can_comment else "BLOCKED (expected on the self-serve tier)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
