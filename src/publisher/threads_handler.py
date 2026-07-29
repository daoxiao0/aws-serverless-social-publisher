"""Lambda entry point: publish the next scheduled Threads post.

A second, independent Lambda alongside handler.py (LinkedIn) rather than a
branch inside it — see ADR-0007. Invoked by its own EventBridge Scheduler
rule. One invocation publishes at most one post, and doing nothing is a valid
outcome — an empty backlog is not an error.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

import boto3

from .content import ContentStore, day_number
from .shorts_parser import ShortsFormatError, parse, threads_state_key
from .state import PUBLISHED, AlreadyPublishedError, PublicationState
from .threads import RefreshedToken, ThreadsClient, TokenExpiredError, refresh_token
from .threads_renderer import render

logger = logging.getLogger()
logger.setLevel(logging.INFO)

METRIC_NAMESPACE = "SocialPublisher"

#: Refresh once life remaining drops below this. Wide margin: unlike
#: LinkedIn's token (ADR-0004), refreshing this one costs nothing and does
#: not invalidate the token being replaced, so there is no reason to wait
#: until the last moment.
REFRESH_MARGIN_DAYS = 14


def lambda_handler(event, context):  # noqa: ARG001 - signature fixed by Lambda
    settings = Settings.from_environment()
    session = boto3.Session()
    secrets_client = session.client("secretsmanager")

    secret = _load_secret(secrets_client, settings.secret_id)
    access_token = _refresh_if_needed(session, secrets_client, settings, secret)

    store = ContentStore(session.client("s3"), settings.bucket, settings.prefix)
    state = PublicationState(session.resource("dynamodb").Table(settings.table))

    key = next_unpublished(store, state)
    if key is None:
        logger.info("nothing left to publish")
        return {"published": False, "reason": "backlog empty"}

    try:
        post = parse(store.read(key))
    except ShortsFormatError as error:
        # Malformed content is a content-repository defect, not a transient
        # publishing failure — surface it loudly rather than retrying.
        raise RuntimeError(f"{key}: {error}") from error

    text = render(post)

    # Claim before posting, never after — see handler.py (LinkedIn) for why.
    try:
        state.claim(post.key)
    except AlreadyPublishedError:
        logger.info("%s was claimed by another invocation", post.key)
        return {"published": False, "reason": "already claimed", "post": post.key}

    if settings.dry_run:
        logger.info("dry run, would publish %s (%d characters)", post.key, len(text))
        state.mark_failed(post.key, "dry run, claim released")
        return {"published": False, "reason": "dry run", "post": post.key}

    client = ThreadsClient(access_token, secret["user_id"])
    try:
        post_id = client.create_post(text)
    except TokenExpiredError as error:
        # Reachable only if the token stopped working between the refresh
        # above and this call — the refresh step is expected to have already
        # caught an actually-dead token.
        state.mark_failed(post.key, "access token invalid even after refresh")
        _notify(session, settings.topic_arn, "Threads token is not usable",
                "Publishing stopped. Re-authorize following docs/setup-threads-app.md.")
        raise error
    except Exception as error:                                    # noqa: BLE001
        state.mark_failed(post.key, repr(error))
        raise

    state.mark_published(post.key, post_id)
    _report_published(session)
    logger.info("published %s as %s", post.key, post_id)
    return {"published": True, "post": post.key, "id": post_id}


def next_unpublished(store: ContentStore, state: PublicationState) -> str | None:
    """The storage key of the earliest Threads derivative not yet posted.

    Keyed through threads_state_key(), not parser.py's LinkedIn-only
    state_key() — the same day number identifies two independent
    publications now, one per platform (see shorts_parser.py).
    """
    for object_key in store.list_posts():
        if state.status_of(threads_state_key(day_number(object_key))) != PUBLISHED:
            return object_key
    return None


class Settings:
    """Configuration, read once from the environment."""

    def __init__(self, bucket, table, secret_id, prefix="", topic_arn="", dry_run=False):
        self.bucket = bucket
        self.table = table
        self.secret_id = secret_id
        self.prefix = prefix
        self.topic_arn = topic_arn
        self.dry_run = dry_run

    @classmethod
    def from_environment(cls) -> "Settings":
        try:
            return cls(
                bucket=os.environ["CONTENT_BUCKET"],
                table=os.environ["STATE_TABLE"],
                secret_id=os.environ["TOKEN_SECRET_ID"],
                prefix=os.environ.get("CONTENT_PREFIX", ""),
                topic_arn=os.environ.get("ALERT_TOPIC_ARN", ""),
                dry_run=os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes"),
            )
        except KeyError as missing:
            raise RuntimeError("missing required environment variable: %s" % missing) from missing


def _report_published(session) -> None:
    """Emit a heartbeat so silence becomes detectable (ADR-0006).

    Under a Threads-specific metric name, distinct from LinkedIn's
    PostsPublished, so the two platforms' silence alarms stay independent —
    one platform going quiet should not be masked by the other still
    publishing.
    """
    session.client("cloudwatch").put_metric_data(
        Namespace=METRIC_NAMESPACE,
        MetricData=[{"MetricName": "ThreadsPostsPublished", "Value": 1, "Unit": "Count"}],
    )


def _load_secret(secrets_client, secret_id: str) -> dict:
    payload = secrets_client.get_secret_value(SecretId=secret_id)
    return json.loads(payload["SecretString"])


def _refresh_if_needed(session, secrets_client, settings: "Settings", secret: dict) -> str:
    """Refresh the token if it is getting old, and report how much life is left.

    Threads, unlike LinkedIn, allows refreshing a still-valid token — see
    ADR-0007. Doing this early and often keeps the token in Secrets Manager
    rarely more than REFRESH_MARGIN_DAYS from its full 60-day lifetime, which
    is what makes the expiry alarm mostly theoretical here rather than the
    monthly chore it is for LinkedIn (ADR-0004).
    """
    remaining = _days_until(secret.get("expires_at"))
    if remaining is not None and remaining > REFRESH_MARGIN_DAYS:
        _put_metric(session, "ThreadsDaysUntilTokenExpiry", remaining)
        return secret["access_token"]

    try:
        refreshed: RefreshedToken = refresh_token(secret["access_token"])
    except TokenExpiredError as error:
        _notify(session, settings.topic_arn, "Threads token refresh failed",
                "The stored token could not be refreshed. Re-authorize following "
                "docs/setup-threads-app.md.")
        raise error

    secret["access_token"] = refreshed.access_token
    secret["expires_at"] = refreshed.expires_at.isoformat()
    secrets_client.put_secret_value(SecretId=settings.secret_id, SecretString=json.dumps(secret))

    remaining = (refreshed.expires_at - datetime.now(timezone.utc)).total_seconds() / 86400
    logger.info("refreshed Threads token, now valid for %.1f more days", remaining)
    _put_metric(session, "ThreadsDaysUntilTokenExpiry", remaining)
    return refreshed.access_token


def _put_metric(session, name: str, value: float) -> None:
    session.client("cloudwatch").put_metric_data(
        Namespace=METRIC_NAMESPACE,
        MetricData=[{"MetricName": name, "Value": value, "Unit": "Count"}],
    )


def _days_until(expires_at: str | None) -> float | None:
    """Fallback for a secret that has never been refreshed by this Lambda."""
    if not expires_at:
        return None
    delta = datetime.fromisoformat(expires_at) - datetime.now(timezone.utc)
    return delta.total_seconds() / 86400


def _notify(session, topic_arn: str, subject: str, message: str) -> None:
    if not topic_arn:
        logger.warning("no alert topic configured; not sending: %s", subject)
        return
    session.client("sns").publish(TopicArn=topic_arn, Subject=subject, Message=message)
