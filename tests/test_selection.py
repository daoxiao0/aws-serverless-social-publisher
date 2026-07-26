"""Which post goes out next.

Storage keys and state keys are different namespaces. Confusing them does not
raise: every post looks unpublished, the run always picks the first file, and
the pipeline stops advancing while still reporting success.
"""

from test_content import FakeS3
from test_state import FakeTable

from publisher.content import ContentStore
from publisher.handler import next_unpublished
from publisher.state import PUBLISHED, PublicationState

KEYS = ["posts/day01_a.md", "posts/day02_b.md", "posts/day03_c.md"]


def build(published_days=()):
    store = ContentStore(FakeS3(KEYS), "bucket", "posts/")
    items = {
        "POST#DAY%02d" % d: {"pk": "POST#DAY%02d" % d, "status": PUBLISHED}
        for d in published_days
    }
    return store, PublicationState(FakeTable(items))


def test_picks_the_first_post_when_nothing_has_been_published():
    store, state = build()
    assert next_unpublished(store, state) == "posts/day01_a.md"


def test_skips_days_already_published():
    store, state = build(published_days=(1, 2))
    assert next_unpublished(store, state) == "posts/day03_c.md"


def test_returns_none_once_everything_has_gone_out():
    store, state = build(published_days=(1, 2, 3))
    assert next_unpublished(store, state) is None


def test_a_gap_in_the_middle_is_picked_up():
    # day02 failed and was left behind; it should go out before day03.
    store, state = build(published_days=(1, 3))
    assert next_unpublished(store, state) == "posts/day02_b.md"


def test_state_is_looked_up_by_state_key_not_storage_key():
    store, state = build(published_days=(1,))
    looked_up = []

    original = state.status_of
    state.status_of = lambda key: (looked_up.append(key), original(key))[1]
    next_unpublished(store, state)

    assert looked_up[0] == "POST#DAY01"
    assert not any(k.startswith("posts/") for k in looked_up)
