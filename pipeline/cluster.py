"""Incremental clustering: new articles join events, new events join stories.

Each article is scored against every event that is still open by average-link
similarity (its mean cosine similarity to the event's articles). At or above
EVENT_SIM it joins the best one; otherwise it starts a new event, which is
scored the same way against open stories' latest articles at STORY_SIM.
"""

import hashlib
from dataclasses import dataclass, field

import numpy as np

from . import config
from .models import Article, ArticleRef, Event, Story
from .normalize import from_iso


def event_id_for(first_article_id: str) -> str:
    return "e" + hashlib.sha1(first_article_id.encode()).hexdigest()[:10]


def story_id_for(first_event_id: str) -> str:
    return "s" + hashlib.sha1(first_event_id.encode()).hexdigest()[:10]


class CentroidIndex:
    """Running sums of unit vectors per cluster, with open/closed time windows.

    sum·v / n is the average cosine similarity between v and the cluster's members.
    """

    def __init__(self, dim: int):
        self.ids: list[str] = []
        self.row: dict[str, int] = {}
        self.sums = np.zeros((0, dim), np.float32)
        self.counts = np.zeros(0)
        self.first = np.zeros(0)  # epoch seconds
        self.last = np.zeros(0)

    def add(self, key: str, vec: np.ndarray, first: float, last: float) -> None:
        if key not in self.row:
            self.row[key] = len(self.ids)
            self.ids.append(key)
            self.sums = np.vstack([self.sums, np.zeros_like(vec)[None, :]])
            self.counts = np.append(self.counts, 0)
            self.first = np.append(self.first, first)
            self.last = np.append(self.last, last)
        i = self.row[key]
        self.sums[i] += vec
        self.counts[i] += 1
        self.first[i] = min(self.first[i], first)
        self.last[i] = max(self.last[i], last)

    def centroid(self, key: str) -> np.ndarray:
        v = self.sums[self.row[key]]
        return v / (np.linalg.norm(v) or 1.0)

    def best(self, vec: np.ndarray, open_mask: np.ndarray) -> tuple[str | None, float]:
        if not open_mask.any():
            return None, -1.0
        idx = np.flatnonzero(open_mask)
        sims = (self.sums[idx] @ vec) / self.counts[idx]
        j = int(np.argmax(sims))
        return self.ids[idx[j]], float(sims[j])


@dataclass
class ClusterResult:
    touched_events: set[str] = field(default_factory=set)
    touched_stories: set[str] = field(default_factory=set)
    event_index: CentroidIndex | None = None


def _ts(iso: str) -> float:
    return from_iso(iso).timestamp()


def assign(
    new: list[Article],
    window: list[Article],
    vecs: dict[str, np.ndarray],
    events: dict[str, Event],
    stories: dict[str, Story],
) -> ClusterResult:
    """Mutates `new` (sets event_id), `events` and `stories` in place."""
    dim = next(iter(vecs.values())).shape[0] if vecs else 384
    ev_index, st_index = CentroidIndex(dim), CentroidIndex(dim)

    story_members: dict[str, list[Article]] = {}
    for a in window:
        e = events.get(a.event_id or "")
        if e is None or a.id not in vecs:
            continue
        ev_index.add(e.id, vecs[a.id], _ts(e.first_seen), _ts(e.last_seen))
        if e.story_id in stories:
            story_members.setdefault(e.story_id, []).append(a)
    for sid, members in story_members.items():
        s = stories[sid]
        for a in sorted(members, key=lambda a: a.published_at)[-config.STORY_CENTROID_ARTICLES :]:
            st_index.add(sid, vecs[a.id], _ts(s.first_seen), _ts(s.last_seen))

    result = ClusterResult(event_index=ev_index)
    event_gap = config.EVENT_GAP.total_seconds()
    event_span = config.EVENT_MAX_SPAN.total_seconds()
    story_gap = config.STORY_GAP.total_seconds()

    for a in sorted(new, key=lambda a: (a.published_at, a.id)):
        v, t = vecs[a.id], _ts(a.published_at)
        open_events = (ev_index.last >= t - event_gap) & (ev_index.first >= t - event_span)
        eid, sim = ev_index.best(v, open_events)

        if eid is not None and sim >= config.EVENT_SIM:
            e = events[eid]
            e.articles.append(ArticleRef.of(a))
            e.first_seen = min(e.first_seen, a.published_at)
            e.last_seen = max(e.last_seen, a.published_at)
            s = stories[e.story_id]
        else:
            open_stories = st_index.last >= t - story_gap
            sid, ssim = st_index.best(v, open_stories)
            eid = event_id_for(a.id)
            if sid is not None and ssim >= config.STORY_SIM:
                s = stories[sid]
            else:
                s = Story(id=story_id_for(eid), first_seen=a.published_at, last_seen=a.published_at)
                stories[s.id] = s
            e = Event(
                id=eid,
                story_id=s.id,
                first_seen=a.published_at,
                last_seen=a.published_at,
                topic=a.topic,
                headline=a.title,
                blurb=a.blurb,
                headline_article_id=a.id,
                articles=[ArticleRef.of(a)],
            )
            events[eid] = e
            s.event_ids.append(eid)

        s.first_seen = min(s.first_seen, a.published_at)
        s.last_seen = max(s.last_seen, a.published_at)
        a.event_id = e.id
        ev_index.add(e.id, v, _ts(e.first_seen), _ts(e.last_seen))
        st_index.add(s.id, v, _ts(s.first_seen), _ts(s.last_seen))
        result.touched_events.add(e.id)
        result.touched_stories.add(s.id)

    return result
