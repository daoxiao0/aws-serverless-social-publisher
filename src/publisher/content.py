"""Reading post files out of the S3 mirror.

S3 holds a copy of the content repository, refreshed on push. Nothing here
writes to it; see docs/adr/0001-content-source-is-mirrored-to-s3.md.
"""

from __future__ import annotations

import re

_DAY_IN_KEY = re.compile(r"day(\d+)", re.IGNORECASE)


class ContentStore:
    """Lists and reads post files from a bucket.

    Args:
        client: a ``boto3`` S3 client.
        bucket: bucket holding the mirror.
        prefix: key prefix under which the posts live.
    """

    def __init__(self, client, bucket: str, prefix: str = ""):
        self._client = client
        self._bucket = bucket
        self._prefix = prefix

    def list_posts(self) -> list[str]:
        """Every post key, ordered by day number rather than lexically.

        Sorting matters: ``day9`` sorts after ``day10`` as a string, which
        would publish the backlog out of order.
        """
        keys = []
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket, Prefix=self._prefix):
            for item in page.get("Contents", []):
                key = item["Key"]
                if key.endswith(".md") and _DAY_IN_KEY.search(key):
                    keys.append(key)
        return sorted(keys, key=day_number)

    def read(self, key: str) -> str:
        body = self._client.get_object(Bucket=self._bucket, Key=key)["Body"]
        return body.read().decode("utf-8")


def day_number(key: str) -> int:
    """Extract the day number from a key, for ordering."""
    match = _DAY_IN_KEY.search(key)
    if match is None:
        raise ValueError("no day number in key: %s" % key)
    return int(match.group(1))
