"""Lambda entry point: publish the next scheduled post.

Invoked by EventBridge Scheduler. One invocation publishes at most one post,
and doing nothing is a valid outcome — an empty backlog is not an error.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

import boto3

from .content import ContentStore
from .linkedin import LinkedInClient, TokenExpiredError
from .parser import parse
from .renderer import render
from .state import AlreadyPublishedError, PublicationState

logger = logging.getLogger()
logger.setLevel(logging.INFO)

METRIC_NAMESPACE = "SocialPublisher"


def lambda_handler(event, context):  # noqa: ARG001 - signature fixed by Lambda
    settings = Settings.from_environment()
    session = boto3.Session()

    secret = _load_secret(session, settings.secret_id)
    _report_token_lifetime(session, secret.get("expires_at"))

    store = ContentStore(session.client("s3"), settings.bucket, settings.prefix)
    state = PublicationState(session.resource("dynamodb").Table(settings.table))

    key = state.first_unpublished(store.list_posts())
    if key is None:
        logger.info("nothing left to publish")
        return {"published": False, "reason": "backlog empty"}

    post = parse(store.read(key))
    text = render(post)

    # Claim before posting, never after. If the process dies between the two,
    # the post is left IN_PROGRESS and needs a human; the opposite order would
    # publish the same content twice.
    try:
        state.claim(post.key)
    except AlreadyPublishedError:
        logger.info("%s was claimed by another invocation", post.key)
        return {"published": False, "reason": "already claimed", "post": post.key}

    if settings.dry_run:
        logger.info("dry run, would publish %s (%d characters)", post.key, len(text))
        state.mark_failed(post.key, "dry run, claim released")
        return {"published": False, "reason": "dry run", "post": post.key}

    client = LinkedInClient(secret["access_token"])
    try:
        urn = client.create_post(text, visibility=settings.visibility)
    except TokenExpiredError as error:
        # Not retryable by definition: there is no refresh token to use.
        state.mark_failed(post.key, "access token expired")
        _notify(session, settings.topic_arn, "LinkedIn token expired",
                "Publishing stopped. Re-authorize following docs/setup-linkedin-app.md.")
        raise error
    except Exception as error:                                    # noqa: BLE001
        state.mark_failed(post.key, repr(error))
        raise

    state.mark_published(post.key, urn)
    logger.info("published %s as %s", post.key, urn)
    return {"published": True, "post": post.key, "urn": urn}


class Settings:
    """Configuration, read once from the environment."""

    def __init__(self, bucket, table, secret_id, prefix="", topic_arn="",
                 visibility="PUBLIC", dry_run=False):
        self.bucket = bucket
        self.table = table
        self.secret_id = secret_id
        self.prefix = prefix
        self.topic_arn = topic_arn
        self.visibility = visibility
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
                visibility=os.environ.get("POST_VISIBILITY", "PUBLIC"),
                dry_run=os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes"),
            )
        except KeyError as missing:
            raise RuntimeError("missing required environment variable: %s" % missing) from missing


def _load_secret(session, secret_id: str) -> dict:
    payload = session.client("secretsmanager").get_secret_value(SecretId=secret_id)
    return json.loads(payload["SecretString"])


def _report_token_lifetime(session, expires_at: str | None) -> None:
    """Publish days-until-expiry so an alarm can fire before things break.

    The token cannot be refreshed programmatically, so this metric is the only
    warning available. See docs/adr/0004-access-token-lifecycle.md.
    """
    if not expires_at:
        logger.warning("secret has no expires_at; token expiry cannot be monitored")
        return
    remaining = (datetime.fromisoformat(expires_at) - datetime.now(timezone.utc)).days
    logger.info("access token expires in %d days", remaining)
    session.client("cloudwatch").put_metric_data(
        Namespace=METRIC_NAMESPACE,
        MetricData=[{"MetricName": "DaysUntilTokenExpiry", "Value": remaining, "Unit": "Count"}],
    )


def _notify(session, topic_arn: str, subject: str, message: str) -> None:
    if not topic_arn:
        logger.warning("no alert topic configured; not sending: %s", subject)
        return
    session.client("sns").publish(TopicArn=topic_arn, Subject=subject, Message=message)
