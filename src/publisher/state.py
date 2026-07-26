"""Publication state, kept in DynamoDB.

The table answers exactly one question: has this post already gone out?
Filenames and folders do not, which is why this exists — see
docs/adr/0002-publication-state-lives-in-dynamodb.md.
"""

from __future__ import annotations

from datetime import datetime, timezone

from botocore.exceptions import ClientError

PENDING = "PENDING"
IN_PROGRESS = "IN_PROGRESS"
PUBLISHED = "PUBLISHED"
FAILED = "FAILED"


class AlreadyPublishedError(RuntimeError):
    """Something else already published this post."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class PublicationState:
    """Thin wrapper over the state table.

    Args:
        table: a ``boto3`` DynamoDB Table resource.
    """

    def __init__(self, table):
        self._table = table

    def status_of(self, key: str) -> str:
        item = self._table.get_item(Key={"pk": key}).get("Item")
        return item["status"] if item else PENDING

    def claim(self, key: str) -> None:
        """Reserve `key` for publishing.

        The conditional write is what makes publishing idempotent: if a
        previous invocation already published this post, or another one is
        publishing it right now, the condition fails and nothing is sent.

        Raises:
            AlreadyPublishedError: if the post is not available to claim.
        """
        try:
            self._table.put_item(
                Item={"pk": key, "status": IN_PROGRESS, "claimed_at": _now()},
                # Absent means never attempted. FAILED means a previous run
                # left it behind and it is safe to pick up again.
                ConditionExpression=(
                    "attribute_not_exists(pk) OR #s IN (:pending, :failed)"
                ),
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":pending": PENDING, ":failed": FAILED},
            )
        except ClientError as error:
            if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise AlreadyPublishedError(
                    "%s is already published or in progress" % key
                ) from error
            raise

    def mark_published(self, key: str, urn: str) -> None:
        self._table.update_item(
            Key={"pk": key},
            UpdateExpression="SET #s = :s, posted_at = :t, post_urn = :u",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": PUBLISHED, ":t": _now(), ":u": urn},
        )

    def mark_failed(self, key: str, reason: str) -> None:
        """Release the claim and record why, so the next run retries it."""
        self._table.update_item(
            Key={"pk": key},
            UpdateExpression=(
                "SET #s = :s, last_error = :e, failed_at = :t "
                "ADD retry_count :one"
            ),
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":s": FAILED,
                ":e": reason[:1000],
                ":t": _now(),
                ":one": 1,
            },
        )

