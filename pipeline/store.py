"""Reads and writes the JSON state kept in the data directory (the `data` branch).

Layout:
    articles/YYYY-MM-DD.jsonl   raw ingest log, by publish date, pruned after ARTICLE_RETENTION
    events/YYYY-MM.json         events by month first seen
    stories.json                stories active within STORY_ARCHIVE_AFTER
    archive/stories-YYYY-MM.json  older stories, by month last seen
    feed_state.json             per-feed ETag / Last-Modified / failure count
    runs.jsonl                  one line per pipeline run
"""

import json
from datetime import datetime
from pathlib import Path

from .models import Article, Event, Story


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


class DataStore:
    def __init__(self, root: Path):
        self.root = root
        self.articles_dir = root / "articles"
        self.events_dir = root / "events"
        self.archive_dir = root / "archive"

    # --- articles ---

    def load_articles(self, since: datetime) -> list[Article]:
        """Articles published on or after `since` (whole days, so a little extra)."""
        cutoff = since.strftime("%Y-%m-%d")
        out = []
        for path in sorted(self.articles_dir.glob("*.jsonl")):
            if path.stem < cutoff:
                continue
            with path.open(encoding="utf-8") as f:
                out.extend(Article(**json.loads(line)) for line in f if line.strip())
        return out

    def append_articles(self, articles: list[Article]) -> None:
        by_day: dict[str, list[Article]] = {}
        for a in articles:
            by_day.setdefault(a.published_at[:10], []).append(a)
        self.articles_dir.mkdir(parents=True, exist_ok=True)
        for day, items in by_day.items():
            with (self.articles_dir / f"{day}.jsonl").open("a", encoding="utf-8") as f:
                for a in sorted(items, key=lambda a: (a.published_at, a.id)):
                    f.write(json.dumps(a.to_dict(), ensure_ascii=False) + "\n")

    def prune_articles(self, before: datetime) -> int:
        cutoff = before.strftime("%Y-%m-%d")
        removed = 0
        for path in self.articles_dir.glob("*.jsonl"):
            if path.stem < cutoff:
                path.unlink()
                removed += 1
        return removed

    # --- events ---

    def load_events(self) -> dict[str, Event]:
        events: dict[str, Event] = {}
        for path in sorted(self.events_dir.glob("*.json")):
            for d in _read_json(path, {}).values():
                events[d["id"]] = Event.from_dict(d)
        return events

    def save_events(self, events: dict[str, Event]) -> None:
        by_month: dict[str, list[Event]] = {}
        for e in events.values():
            by_month.setdefault(e.first_seen[:7], []).append(e)
        for path in self.events_dir.glob("*.json"):
            if path.stem not in by_month:
                path.unlink()
        for month, items in by_month.items():
            items.sort(key=lambda e: (e.first_seen, e.id))
            _write_json(self.events_dir / f"{month}.json", {e.id: e.to_dict() for e in items})

    def archive_events(self, events: list[Event]) -> None:
        by_month: dict[str, list[Event]] = {}
        for e in events:
            by_month.setdefault(e.first_seen[:7], []).append(e)
        for month, items in by_month.items():
            path = self.archive_dir / f"events-{month}.json"
            existing = _read_json(path, {})
            existing.update({e.id: e.to_dict() for e in items})
            _write_json(path, existing)

    # --- stories ---

    def load_stories(self) -> dict[str, Story]:
        return {d["id"]: Story.from_dict(d) for d in _read_json(self.root / "stories.json", {}).values()}

    def save_stories(self, stories: dict[str, Story]) -> None:
        items = sorted(stories.values(), key=lambda s: (s.first_seen, s.id))
        _write_json(self.root / "stories.json", {s.id: s.to_dict() for s in items})

    def archive_stories(self, stories: list[Story]) -> None:
        by_month: dict[str, list[Story]] = {}
        for s in stories:
            by_month.setdefault(s.last_seen[:7], []).append(s)
        for month, items in by_month.items():
            path = self.archive_dir / f"stories-{month}.json"
            existing = _read_json(path, {})
            existing.update({s.id: s.to_dict() for s in items})
            _write_json(path, existing)

    # --- feed state and run log ---

    def load_feed_state(self) -> dict[str, dict]:
        return _read_json(self.root / "feed_state.json", {})

    def save_feed_state(self, state: dict[str, dict]) -> None:
        _write_json(self.root / "feed_state.json", dict(sorted(state.items())))

    def append_run(self, record: dict, keep: int) -> None:
        path = self.root / "runs.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
        lines.append(json.dumps(record, ensure_ascii=False))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines[-keep:]) + "\n", encoding="utf-8")

    def load_runs(self, limit: int = 50) -> list[dict]:
        path = self.root / "runs.jsonl"
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines[-limit:] if line.strip()]
