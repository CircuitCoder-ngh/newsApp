"""One pipeline run: fetch → dedupe → embed → cluster → label → housekeeping → save."""

import logging
import time
from datetime import datetime
from pathlib import Path

from . import config
from .cluster import assign
from .embed import Embedder
from .fetch import fetch_all, load_feeds, new_articles, update_feed_state
from .label import relabel_event, relabel_story, story_keywords
from .models import Event, Story
from .normalize import from_iso, now_utc, to_iso
from .store import DataStore

log = logging.getLogger(__name__)


def run(data_dir: Path, cache_dir: Path, feeds_file: Path = config.FEEDS_FILE, now: datetime | None = None) -> dict:
    started = time.monotonic()
    now = now or now_utc()
    store = DataStore(data_dir)

    feeds = load_feeds(feeds_file)
    feed_state = store.load_feed_state()
    results = fetch_all(feeds, feed_state)
    failed = [r for r in results if r.error]
    for r in failed:
        log.warning("feed failed: %s %s (%s)", r.feed.outlet, r.feed.url, r.error)

    window = store.load_articles(since=now - config.EMBED_WINDOW)
    new = new_articles(results, {a.id for a in window}, now)
    events = store.load_events()
    stories = store.load_stories()
    events_before = set(events)
    log.info("fetched %d feeds (%d failed), %d new articles", len(results), len(failed), len(new))

    touched_stories: set[str] = set()
    if new:
        everything = window + new
        vectors = Embedder(cache_dir).embed([a.embed_text for a in everything])
        vecs = {a.id: v for a, v in zip(everything, vectors)}
        result = assign(new, window, vecs, events, stories)
        members = {a.id: a for a in everything}
        for eid in result.touched_events:
            relabel_event(events[eid], members, vecs, result.event_index)
        touched_stories = result.touched_stories
        _relabel_stories(touched_stories, events, stories, now)
        store.append_articles(new)

    dropped, archived = _housekeeping(store, events, stories, now)
    store.prune_articles(before=now - config.ARTICLE_RETENTION)
    store.save_events(events)
    store.save_stories(stories)
    update_feed_state(feed_state, results, now)
    store.save_feed_state(feed_state)

    record = {
        "at": to_iso(now),
        "seconds": round(time.monotonic() - started, 1),
        "feeds": len(results),
        "feeds_failed": [f"{r.feed.outlet}: {r.error}" for r in failed],
        "new_articles": len(new),
        "new_events": len(set(events) - events_before),
        "touched_stories": len(touched_stories),
        "active_stories": len(stories),
        "dropped_singletons": dropped,
        "archived_stories": archived,
    }
    store.append_run(record, keep=config.RUN_LOG_KEEP)
    return record


def _relabel_stories(touched: set[str], events: dict[str, Event], stories: dict[str, Story], now: datetime) -> None:
    corpus_cutoff = to_iso(now - config.STORY_GAP)
    corpus = {
        s.id: [a.title for eid in s.event_ids if eid in events for a in events[eid].articles]
        for s in stories.values()
        if s.last_seen >= corpus_cutoff or s.id in touched
    }
    keywords = story_keywords(corpus)
    for sid in touched:
        stories[sid].keywords = keywords.get(sid, [])
        relabel_story(stories[sid], events)


def _housekeeping(store: DataStore, events: dict[str, Event], stories: dict[str, Story], now: datetime) -> tuple[int, int]:
    """Drop closed one-article stories; archive stories inactive for a long time."""
    dropped = 0
    for s in list(stories.values()):
        if from_iso(s.last_seen) >= now - config.STORY_GAP or len(s.event_ids) != 1:
            continue
        e = events.get(s.event_ids[0])
        if e is None or len(e.outlets) == 1:
            events.pop(s.event_ids[0], None)
            del stories[s.id]
            dropped += 1

    stale = [s for s in stories.values() if from_iso(s.last_seen) < now - config.STORY_ARCHIVE_AFTER]
    if stale:
        store.archive_stories(stale)
        store.archive_events([events.pop(eid) for s in stale for eid in s.event_ids if eid in events])
        for s in stale:
            del stories[s.id]
    return dropped, len(stale)
