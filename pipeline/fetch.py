"""Fetch RSS/Atom feeds and turn their items into new Articles."""

import asyncio
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import feedparser
import httpx
import yaml

from . import config
from .models import Article
from .normalize import (
    article_id,
    canonical_url,
    clean_blurb,
    html_to_text,
    struct_to_datetime,
    to_iso,
    truncate,
)


@dataclass
class Feed:
    outlet: str
    region: str
    topic: str
    url: str
    exclude_url: list[re.Pattern] = field(default_factory=list)
    exclude_title: list[re.Pattern] = field(default_factory=list)

    def excludes(self, url: str, title: str) -> bool:
        return any(p.search(url) for p in self.exclude_url) or any(p.search(title) for p in self.exclude_title)


@dataclass
class FeedItem:
    url: str
    title: str
    blurb: str
    published: datetime | None


@dataclass
class FeedResult:
    feed: Feed
    status: int | None = None
    items: list[FeedItem] = field(default_factory=list)
    error: str | None = None
    etag: str | None = None
    last_modified: str | None = None


def load_feeds(path: Path = config.FEEDS_FILE) -> list[Feed]:
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    defaults = cfg.get("defaults", {})

    def compile_all(*lists):
        return [re.compile(p, re.IGNORECASE) for lst in lists for p in (lst or [])]

    feeds = []
    for outlet in cfg["outlets"]:
        exclude_url = compile_all(defaults.get("exclude_url_patterns"), outlet.get("exclude_url_patterns"))
        exclude_title = compile_all(defaults.get("exclude_title_patterns"), outlet.get("exclude_title_patterns"))
        for f in outlet["feeds"]:
            if f["topic"] not in config.TOPICS:
                raise ValueError(f"{outlet['name']}: unknown topic {f['topic']!r}")
            feeds.append(Feed(outlet["name"], outlet["region"], f["topic"], f["url"], exclude_url, exclude_title))
    return feeds


def parse_feed(content: bytes) -> list[FeedItem]:
    parsed = feedparser.parse(content)
    items = []
    for entry in parsed.entries:
        url = entry.get("link")
        title = html_to_text(entry.get("title"))
        if not url or not title:
            continue
        blurb = clean_blurb(html_to_text(entry.get("summary") or entry.get("description")))
        if blurb.lower() == title.lower():
            blurb = ""
        published = struct_to_datetime(entry.get("published_parsed") or entry.get("updated_parsed"))
        items.append(FeedItem(url, title, truncate(blurb, config.BLURB_MAX_CHARS), published))
    return items


async def _fetch_one(client: httpx.AsyncClient, feed: Feed, state: dict) -> FeedResult:
    headers = {}
    if state.get("etag"):
        headers["If-None-Match"] = state["etag"]
    if state.get("last_modified"):
        headers["If-Modified-Since"] = state["last_modified"]
    result = FeedResult(feed)
    try:
        resp = await client.get(feed.url, headers=headers)
        result.status = resp.status_code
        if resp.status_code == 304:
            result.etag, result.last_modified = state.get("etag"), state.get("last_modified")
            return result
        resp.raise_for_status()
        result.items = parse_feed(resp.content)
        result.etag = resp.headers.get("etag")
        result.last_modified = resp.headers.get("last-modified")
        if not result.items:
            result.error = "no items"
    except (httpx.HTTPError, ValueError) as ex:
        result.error = f"{type(ex).__name__}: {ex}"[:200]
    return result


async def _fetch_all(feeds: list[Feed], feed_state: dict[str, dict]) -> list[FeedResult]:
    sem = asyncio.Semaphore(config.FETCH_CONCURRENCY)
    async with httpx.AsyncClient(
        headers={"User-Agent": config.USER_AGENT},
        timeout=config.FETCH_TIMEOUT_SECONDS,
        follow_redirects=True,
    ) as client:

        async def run(feed: Feed) -> FeedResult:
            async with sem:
                return await _fetch_one(client, feed, feed_state.get(feed.url, {}))

        return await asyncio.gather(*(run(f) for f in feeds))


def fetch_all(feeds: list[Feed], feed_state: dict[str, dict]) -> list[FeedResult]:
    return asyncio.run(_fetch_all(feeds, feed_state))


def update_feed_state(feed_state: dict[str, dict], results: list[FeedResult], now: datetime) -> None:
    for r in results:
        s = feed_state.setdefault(r.feed.url, {"outlet": r.feed.outlet})
        if r.error:
            s["failures"] = s.get("failures", 0) + 1
            s["last_error"] = r.error
            s["last_error_at"] = to_iso(now)
        else:
            s.update(failures=0, last_ok_at=to_iso(now), etag=r.etag, last_modified=r.last_modified)
            if r.status != 304:
                s["last_item_count"] = len(r.items)


def new_articles(results: list[FeedResult], known_ids: set[str], now: datetime) -> list[Article]:
    """Filter fetched items down to articles we haven't seen, within the age window."""
    oldest = now - config.MAX_ARTICLE_AGE
    seen = set(known_ids)
    out = []
    for r in results:
        for item in r.items:
            url = canonical_url(item.url)
            aid = article_id(url)
            if aid in seen or r.feed.excludes(url, item.title):
                continue
            published = item.published or now
            if published > now + timedelta(minutes=5):
                # Feeds that label local time as GMT run whole hours ahead; undo that offset.
                published -= timedelta(hours=math.ceil((published - now) / timedelta(hours=1)))
            published = min(published, now)
            if published < oldest:
                continue
            seen.add(aid)
            out.append(
                Article(
                    id=aid,
                    url=url,
                    outlet=r.feed.outlet,
                    region=r.feed.region,
                    topic=r.feed.topic,
                    title=item.title,
                    blurb=item.blurb,
                    published_at=to_iso(published),
                    fetched_at=to_iso(now),
                )
            )
    return out
