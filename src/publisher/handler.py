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

from .content import ContentStore, day_number
from .linkedin import LinkedInClient, TokenExpiredError, introspect
from .parser import parse, state_key
from .renderer import render
from .state import PUBLISHED, AlreadyPublishedError, PublicationState

logger = logging.getLogger()
logger.setLevel(logging.INFO)

METRIC_NAMESPACE = "SocialPublisher"

#: Without this scope the token cannot create posts, so there is no point
#: reaching the LinkedIn call to find out.
POSTING_SCOPE = "w_member_social"


def lambda_handler(event, context):  # noqa: ARG001 - signature fixed by Lambda
    settings = Settings.from_environment()
    session = boto3.Session()

    secret = _load_secret(session, settings.secret_id)
    _check_token(session, settings, secret)

    store = ContentStore(session.client("s3"), settings.bucket, settings.prefix)
    state = PublicationState(session.resource("dynamodb").Table(settings.table))

    key = next_unpublished(store, state)
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
    _report_published(session)
    logger.info("published %s as %s", post.key, urn)
    return {"published": True, "post": post.key, "urn": urn}


def next_unpublished(store: ContentStore, state: PublicationState) -> str | None:
    """The storage key of the earliest post that has not gone out yet.

    Storage keys and state keys are different namespaces: the object is
    `posts/day13_title.md`, the state row is `POST#DAY13`. Looking a post up
    by its storage key silently finds nothing, so every post looks unpublished
    and the run always picks the first file.
    """
    for object_key in store.list_posts():
        if state.status_of(state_key(day_number(object_key))) != PUBLISHED:
            return object_key
    return None


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


def _report_published(session) -> None:
    """Emit a heartbeat so silence becomes detectable.

    Every early return in this function is a legitimate outcome that produces
    no error and no log line worth alarming on — an empty backlog, a post
    already claimed, a dry run. That is precisely how a broken pipeline can
    report success indefinitely. An alarm on the absence of this metric is the
    only thing that notices. See docs/adr/0006-verifying-what-was-published.md.
    """
    session.client("cloudwatch").put_metric_data(
        Namespace=METRIC_NAMESPACE,
        MetricData=[{"MetricName": "PostsPublished", "Value": 1, "Unit": "Count"}],
    )


def _load_secret(session, secret_id: str) -> dict:
    payload = session.client("secretsmanager").get_secret_value(SecretId=secret_id)
    return json.loads(payload["SecretString"])


def _check_token(session, settings: "Settings", secret: dict) -> None:
    """Verify the token and publish how much life it has left.

    The token cannot be refreshed programmatically, so this metric is the only
    warning available before publishing stops. See
    docs/adr/0004-access-token-lifecycle.md.
    """
    info = None
    if secret.get("client_id") and secret.get("client_secret"):
        info = introspect(secret["access_token"], secret["client_id"], secret["client_secret"])
    else:
        logger.warning(
            "no client credentials in the secret; falling back to the stored "
            "expires_at, which nothing verifies"
        )

    remaining = info.days_remaining if info else _days_until(secret.get("expires_at"))
    if remaining is None:
        logger.warning("token expiry is unknown; it cannot be monitored")
    else:
        logger.info("access token expires in %.1f days", remaining)
        session.client("cloudwatch").put_metric_data(
            Namespace=METRIC_NAMESPACE,
            MetricData=[
                {"MetricName": "DaysUntilTokenExpiry", "Value": remaining, "Unit": "Count"}
            ],
        )

    if info is None:
        return

    # Expiry is not the only way a token stops working: LinkedIn can revoke
    # one at any time for technical or policy reasons.
    if not info.active:
        _notify(session, settings.topic_arn, "LinkedIn token is not usable",
                "Introspection reports status=%s. Re-authorize following "
                "docs/setup-linkedin-app.md." % info.status)
        raise TokenExpiredError("token is not active (status=%s)" % info.status)

    if not info.grants(POSTING_SCOPE):
        _notify(session, settings.topic_arn, "LinkedIn token is missing a scope",
                "The token does not grant %s, so it cannot publish. Scopes: %s"
                % (POSTING_SCOPE, ", ".join(sorted(info.scopes)) or "none"))
        raise RuntimeError("token does not grant %s" % POSTING_SCOPE)


def _days_until(expires_at: str | None) -> float | None:
    """Fallback for secrets that carry only a hand-entered expiry."""
    if not expires_at:
        return None
    delta = datetime.fromisoformat(expires_at) - datetime.now(timezone.utc)
    return delta.total_seconds() / 86400


def _notify(session, topic_arn: str, subject: str, message: str) -> None:
    if not topic_arn:
        logger.warning("no alert topic configured; not sending: %s", subject)
        return
    session.client("sns").publish(TopicArn=topic_arn, Subject=subject, Message=message)
