"""Clustering on hand-built vectors with known similarities.

e1 vs e1: 1.0 (same event); e1 vs normalize(e1+e2): 0.707 (same story, different
event: below EVENT_SIM, above STORY_SIM); e1 vs e3: 0 (unrelated).
"""

from datetime import UTC, datetime, timedelta

import numpy as np

from pipeline.cluster import assign, event_id_for, story_id_for
from pipeline.models import Article
from pipeline.normalize import to_iso

T0 = datetime(2026, 10, 29, 8, 0, tzinfo=UTC)
E = np.eye(8, dtype=np.float32)
SAME = E[0]
RELATED = (E[0] + E[1]) / np.sqrt(2)
OTHER = E[2]


def art(aid: str, hours: float, outlet: str = "A") -> Article:
    return Article(
        id=aid,
        url=f"https://x.com/{aid}",
        outlet=outlet,
        region="Europe",
        topic="world",
        title=f"title {aid}",
        blurb="",
        published_at=to_iso(T0 + timedelta(hours=hours)),
        fetched_at=to_iso(T0 + timedelta(hours=hours)),
    )


def test_events_and_stories():
    a1, a2, b1, c1 = art("a1", 0), art("a2", 1, "B"), art("b1", 2), art("c1", 3)
    vecs = {"a1": SAME, "a2": SAME, "b1": RELATED, "c1": OTHER}
    events, stories = {}, {}
    result = assign([c1, b1, a2, a1], [], vecs, events, stories)  # input order shouldn't matter

    assert a1.event_id == a2.event_id == event_id_for("a1")
    assert b1.event_id not in (a1.event_id, c1.event_id)
    assert events[a1.event_id].story_id == events[b1.event_id].story_id == story_id_for(a1.event_id)
    assert events[c1.event_id].story_id != events[a1.event_id].story_id
    assert events[a1.event_id].outlets == ["A", "B"]
    assert stories[story_id_for(a1.event_id)].event_ids == [a1.event_id, b1.event_id]
    assert len(events) == 3 and len(stories) == 2
    assert result.touched_events == set(events) and result.touched_stories == set(stories)


def test_event_closes_after_time_window_but_story_continues():
    a1, later = art("a1", 0), art("a9", 40)
    vecs = {"a1": SAME, "a9": SAME}
    events, stories = {}, {}
    assign([a1, later], [], vecs, events, stories)
    assert later.event_id != a1.event_id
    assert events[later.event_id].story_id == events[a1.event_id].story_id


def test_incremental_run_joins_existing_event():
    a1, a2 = art("a1", 0), art("a2", 1, "B")
    vecs = {"a1": SAME, "a2": SAME, "a3": SAME}
    events, stories = {}, {}
    assign([a1, a2], [], vecs, events, stories)

    a3 = art("a3", 3, "C")
    result = assign([a3], [a1, a2], vecs, events, stories)
    assert a3.event_id == a1.event_id
    assert events[a1.event_id].last_seen == a3.published_at
    assert result.touched_events == {a1.event_id}
    assert len(events) == 1
