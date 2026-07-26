import pytest
from botocore.exceptions import ClientError

from publisher.state import (
    FAILED,
    IN_PROGRESS,
    PENDING,
    PUBLISHED,
    AlreadyPublishedError,
    PublicationState,
)


class FakeTable:
    """Enough of a DynamoDB Table to exercise the conditional write."""

    def __init__(self, items=None):
        self.items = dict(items or {})

    def get_item(self, Key):  # noqa: N803 - boto3 argument casing
        item = self.items.get(Key["pk"])
        return {"Item": item} if item else {}

    def put_item(self, Item, ConditionExpression=None, **_kwargs):  # noqa: N803
        existing = self.items.get(Item["pk"])
        if existing and existing["status"] not in (PENDING, FAILED):
            raise ClientError(
                {"Error": {"Code": "ConditionalCheckFailedException", "Message": "nope"}},
                "PutItem",
            )
        self.items[Item["pk"]] = Item

    def update_item(self, Key, ExpressionAttributeValues, **_kwargs):  # noqa: N803
        item = self.items.setdefault(Key["pk"], {"pk": Key["pk"]})
        item["status"] = ExpressionAttributeValues[":s"]
        if ":u" in ExpressionAttributeValues:
            item["post_urn"] = ExpressionAttributeValues[":u"]
        if ":e" in ExpressionAttributeValues:
            item["last_error"] = ExpressionAttributeValues[":e"]


def test_unknown_post_is_pending():
    assert PublicationState(FakeTable()).status_of("POST#DAY01") == PENDING


def test_claim_marks_in_progress():
    table = FakeTable()
    PublicationState(table).claim("POST#DAY01")
    assert table.items["POST#DAY01"]["status"] == IN_PROGRESS


def test_claiming_a_published_post_is_refused():
    # The guard against publishing the same day twice.
    table = FakeTable({"POST#DAY01": {"pk": "POST#DAY01", "status": PUBLISHED}})
    with pytest.raises(AlreadyPublishedError):
        PublicationState(table).claim("POST#DAY01")


def test_claiming_an_in_progress_post_is_refused():
    table = FakeTable({"POST#DAY01": {"pk": "POST#DAY01", "status": IN_PROGRESS}})
    with pytest.raises(AlreadyPublishedError):
        PublicationState(table).claim("POST#DAY01")


def test_a_failed_post_can_be_claimed_again():
    table = FakeTable({"POST#DAY01": {"pk": "POST#DAY01", "status": FAILED}})
    PublicationState(table).claim("POST#DAY01")
    assert table.items["POST#DAY01"]["status"] == IN_PROGRESS


def test_other_client_errors_are_not_swallowed():
    class Broken(FakeTable):
        def put_item(self, **_kwargs):
            raise ClientError(
                {"Error": {"Code": "ProvisionedThroughputExceededException", "Message": ""}},
                "PutItem",
            )

    with pytest.raises(ClientError):
        PublicationState(Broken()).claim("POST#DAY01")


def test_mark_published_records_the_urn():
    table = FakeTable()
    PublicationState(table).mark_published("POST#DAY01", "urn:li:share:9")
    assert table.items["POST#DAY01"]["status"] == PUBLISHED
    assert table.items["POST#DAY01"]["post_urn"] == "urn:li:share:9"


def test_mark_failed_truncates_long_errors():
    table = FakeTable()
    PublicationState(table).mark_failed("POST#DAY01", "x" * 5000)
    assert len(table.items["POST#DAY01"]["last_error"]) == 1000


