"""End-to-end: run the pipeline over a fake feed source and embedder, then build the site."""

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from pipeline import run as run_module
from pipeline.fetch import FeedItem, FeedResult
from pipeline.site.build import build

NOW = datetime(2026, 10, 29, 14, 0, tzinfo=UTC)

FEEDS_YAML = """
defaults:
  exclude_url_patterns: [/live/]
outlets:
  - name: Alpha News
    region: Europe
    feeds: [{topic: world, url: "https://alpha.example/rss"}]
  - name: Beta Times
    region: Asia-Pacific
    feeds: [{topic: world, url: "https://beta.example/rss"}]
"""

ITEMS = {
    "https://alpha.example/rss": [
        ("https://alpha.example/quake", "Earthquake hits Japan coast", 3),
        ("https://alpha.example/markets", "Markets fall on rate fears", 2),
    ],
    "https://beta.example/rss": [
        ("https://beta.example/quake", "Earthquake hits Japan coast, tsunami warning", 1),
        ("https://beta.example/xss", "<script>alert(1)</script> Bad headline", 1),
    ],
}


class BagOfWordsEmbedder:
    """Deterministic stand-in for fastembed: hashed bag of words, L2-normalized."""

    def __init__(self, cache_dir):
        pass

    def embed(self, texts):
        out = np.zeros((len(texts), 256), np.float32)
        for i, text in enumerate(texts):
            for word in re.findall(r"\w+", text.lower()):
                out[i, int(hashlib.md5(word.encode()).hexdigest(), 16) % 256] += 1
        return out / np.linalg.norm(out, axis=1, keepdims=True)


@pytest.fixture
def env(tmp_path, monkeypatch):
    feeds_file = tmp_path / "feeds.yaml"
    feeds_file.write_text(FEEDS_YAML)

    def fake_fetch_all(feeds, state):
        return [
            FeedResult(f, status=200, items=[FeedItem(u, t, "", NOW - timedelta(hours=h)) for u, t, h in ITEMS[f.url]])
            for f in feeds
        ]

    monkeypatch.setattr(run_module, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(run_module, "Embedder", BagOfWordsEmbedder)
    return tmp_path, feeds_file


def run_at(env, now):
    tmp, feeds_file = env
    return run_module.run(tmp / "data", tmp / "cache", feeds_file, now=now)


def test_run_dedupes_merges_and_housekeeps(env):
    tmp, _ = env
    first = run_at(env, NOW)
    assert (first["new_articles"], first["new_events"], first["active_stories"]) == (4, 3, 3)

    events = json.loads((tmp / "data/events/2026-10.json").read_text())
    quake = next(e for e in events.values() if "Earthquake" in e["headline"])
    assert sorted(a["outlet"] for a in quake["articles"]) == ["Alpha News", "Beta Times"]

    again = run_at(env, NOW + timedelta(hours=1))
    assert again["new_articles"] == 0

    # A week later the two single-outlet stories are dropped; the shared quake story stays.
    week = run_at(env, NOW + timedelta(days=8))
    assert week["dropped_singletons"] == 2 and week["active_stories"] == 1

    # After a month it moves to the archive and the raw article log is pruned.
    month = run_at(env, NOW + timedelta(days=31))
    assert month["archived_stories"] == 1 and month["active_stories"] == 0
    assert list((tmp / "data/archive").glob("stories-*.json"))
    assert not list((tmp / "data/articles").glob("*.jsonl"))
    assert len((tmp / "data/runs.jsonl").read_text().splitlines()) == 4


def test_build_renders_pages_with_relative_links(env):
    tmp, feeds_file = env
    run_at(env, NOW)
    out = tmp / "site"
    pages = build(tmp / "data", out, feeds_file, now=NOW)
    assert pages >= 5

    index = (out / "index.html").read_text()
    assert "Earthquake hits Japan coast" in index
    assert "<script>alert(1)</script>" not in index and "&lt;script&gt;" in index
    assert 'href="/' not in index and 'src="/' not in index
    assert 'aria-label="Covered by 2 outlets: 1 Europe, 1 Asia-Pacific"' in index

    story_pages = [p for p in (out / "stories").glob("s*.html")]
    assert len(story_pages) == 3
    assert 'href="../static/style.css"' in story_pages[0].read_text()
    assert (out / "archive" / "2026-10-29.html").exists()
    assert (out / ".nojekyll").exists()

    # Rebuilding over a previous build is fine; over an unrelated directory it is refused.
    build(tmp / "data", out, feeds_file, now=NOW)
    other = tmp / "precious"
    other.mkdir()
    (other / "notes.txt").write_text("keep me")
    with pytest.raises(SystemExit):
        build(tmp / "data", other, feeds_file, now=NOW)
    assert (other / "notes.txt").exists()
