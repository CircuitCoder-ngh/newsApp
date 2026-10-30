import re
from datetime import UTC, datetime
from pathlib import Path

from pipeline.fetch import Feed, FeedItem, FeedResult, load_feeds, new_articles, parse_feed

FIXTURE = Path(__file__).parent / "fixtures" / "sample_rss.xml"
NOW = datetime(2026, 10, 29, 14, 0, tzinfo=UTC)


def make_feed(**kw) -> Feed:
    defaults = dict(
        outlet="Example News",
        region="Europe",
        topic="world",
        url="https://news.example.com/rss",
        exclude_url=[re.compile("/live/", re.I)],
        exclude_title=[re.compile(r"^opinion\b", re.I)],
    )
    return Feed(**{**defaults, **kw})


def test_parse_feed_cleans_items():
    items = parse_feed(FIXTURE.read_bytes())
    titles = [i.title for i in items]
    assert "Item without a link" not in titles
    quake = items[0]
    assert quake.title == "Earthquake strikes off the coast & triggers tsunami warning"
    assert quake.blurb == "A magnitude 7.1 earthquake struck on Thursday."
    assert quake.published == datetime(2026, 10, 29, 10, 0, tzinfo=UTC)
    rates = next(i for i in items if i.title == "Central bank holds rates")
    assert rates.blurb == ""  # identical to the title


def test_new_articles_filters_excluded_old_and_known():
    result = FeedResult(make_feed(), items=parse_feed(FIXTURE.read_bytes()))
    articles = new_articles([result], set(), NOW)
    assert [a.title for a in articles] == [
        "Earthquake strikes off the coast & triggers tsunami warning",
        "Ministers meet in Geneva",
    ]
    quake = articles[0]
    assert quake.url == "https://news.example.com/world/quake-123"
    assert quake.outlet == "Example News" and quake.topic == "world"
    assert quake.published_at == "2026-10-29T10:00:00Z"

    again = new_articles([result], {a.id for a in articles}, NOW)
    assert again == []


def test_new_articles_dedupes_across_feeds_first_feed_wins():
    item = FeedItem("https://x.com/a", "Same story", "", NOW)
    world = FeedResult(make_feed(topic="world"), items=[item])
    business = FeedResult(make_feed(topic="business"), items=[item])
    articles = new_articles([world, business], set(), NOW)
    assert len(articles) == 1 and articles[0].topic == "world"


def test_future_timestamps_are_pulled_back_by_whole_hours():
    # A feed that labels UTC+2 local time as GMT: published 20 minutes ago, claims 1h40m ahead.
    item = FeedItem("https://x.com/b", "Mislabelled", "", datetime(2026, 10, 29, 15, 40, tzinfo=UTC))
    missing = FeedItem("https://x.com/c", "Undated", "", None)
    articles = new_articles([FeedResult(make_feed(), items=[item, missing])], set(), NOW)
    assert [a.published_at for a in articles] == ["2026-10-29T13:40:00Z", "2026-10-29T14:00:00Z"]


def test_feeds_yaml_is_valid():
    feeds = load_feeds()
    assert len(feeds) > 20
    assert {f.topic for f in feeds} == {"world", "business", "science"}
    assert all(f.exclude_url for f in feeds)
