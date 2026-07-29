"""Which Threads post goes out next.

Same reasoning as test_selection.py (LinkedIn), against the Threads-specific
state key namespace (shorts_parser.threads_state_key) — the same day number
must not be looked up under LinkedIn's POST#DAY key, or every Threads post
would look already published the moment its LinkedIn counterpart went out.
"""

from test_content import FakeS3
from test_state import FakeTable

from publisher.content import ContentStore
from publisher.state import PUBLISHED, PublicationState
from publisher.threads_handler import next_unpublished

KEYS = ["shorts/day01_a.md", "shorts/day02_b.md", "shorts/day03_c.md"]


def build(published_days=()):
    store = ContentStore(FakeS3(KEYS), "bucket", "shorts/")
    items = {
        "THREADS#DAY%02d" % d: {"pk": "THREADS#DAY%02d" % d, "status": PUBLISHED}
        for d in published_days
    }
    return store, PublicationState(FakeTable(items))


def test_picks_the_first_post_when_nothing_has_been_published():
    store, state = build()
    assert next_unpublished(store, state) == "shorts/day01_a.md"


def test_skips_days_already_published():
    store, state = build(published_days=(1, 2))
    assert next_unpublished(store, state) == "shorts/day03_c.md"


def test_returns_none_once_everything_has_gone_out():
    store, state = build(published_days=(1, 2, 3))
    assert next_unpublished(store, state) is None


def test_a_gap_in_the_middle_is_picked_up():
    store, state = build(published_days=(1, 3))
    assert next_unpublished(store, state) == "shorts/day02_b.md"


def test_state_is_looked_up_by_the_threads_namespace_not_linkedins():
    store, state = build(published_days=(1,))
    looked_up = []

    original = state.status_of
    state.status_of = lambda key: (looked_up.append(key), original(key))[1]
    next_unpublished(store, state)

    assert looked_up[0] == "THREADS#DAY01"
    assert not any(k.startswith("POST#") for k in looked_up)
