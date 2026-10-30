"""Render the static site from the data directory."""

import shutil
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .. import config
from ..fetch import load_feeds
from ..models import ArticleRef, Event, Story
from ..normalize import from_iso, now_utc
from ..store import DataStore

HERE = Path(__file__).parent
MARKER = ".worldline-build"

# Display order and CSS class for each outlet region.
REGIONS = {
    "Europe": "eu",
    "Americas": "am",
    "Middle East": "me",
    "Asia-Pacific": "ap",
    "Africa": "af",
}


@dataclass
class Entry:
    """An event as the templates need it."""

    event: Event
    story: Story | None
    sources: list[ArticleRef]
    regions: list[str]  # one CSS region class per outlet, grouped in REGIONS order
    coverage_label: str
    weight: int  # 1-4, drives the marker size on the time spine
    when: datetime  # local time the event was first reported

    @property
    def headline_url(self) -> str:
        lead = next((a for a in self.event.articles if a.id == self.event.headline_article_id), None)
        return (lead or self.sources[0]).url

    @property
    def single(self) -> bool:
        return len(self.sources) < config.MIN_OUTLETS_DEFAULT

    @property
    def region_counts(self) -> dict[str, int]:
        return Counter(self.regions)

    @property
    def story_updates(self) -> int:
        return len(self.story.event_ids) if self.story else 0


@dataclass
class StoryCard:
    story: Story
    regions: list[str]
    coverage_label: str
    topic: str
    single: bool  # no event in the story was reported by more than one outlet
    last: datetime
    first: datetime

    @property
    def region_counts(self) -> dict[str, int]:
        return Counter(self.regions)


def _coverage(outlets: list[str], region_of: dict[str, str]) -> tuple[list[str], str]:
    counts = Counter(region_of.get(o, "Europe") for o in outlets)
    regions = [REGIONS[r] for r in REGIONS for _ in range(counts.get(r, 0))]
    parts = ", ".join(f"{n} {r}" for r in REGIONS if (n := counts.get(r)))
    noun = "outlet" if len(outlets) == 1 else "outlets"
    return regions, f"Covered by {len(outlets)} {noun}: {parts}"


def _weight(n_outlets: int) -> int:
    return 1 if n_outlets < 2 else 2 if n_outlets < 5 else 3 if n_outlets < 10 else 4


class SiteBuilder:
    def __init__(self, data_dir: Path, out_dir: Path, feeds_file: Path = config.FEEDS_FILE, now: datetime | None = None):
        self.store = DataStore(data_dir)
        self.out = out_dir
        self.now = now or now_utc()
        self.tz = ZoneInfo(config.SITE_TIMEZONE)
        self.events = self.store.load_events()
        self.stories = self.store.load_stories()
        feeds = load_feeds(feeds_file)
        self.region_of = {f.outlet: f.region for f in feeds}
        self.outlet_total = len(self.region_of)
        self.env = Environment(
            loader=FileSystemLoader(HERE / "templates"),
            autoescape=select_autoescape(),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self.env.filters.update(clock=self.clock, dayname=self.dayname, longdate=self.longdate, stamp=self.stamp)
        self.pages = 0

    # --- formatting ---

    def local(self, iso_or_dt) -> datetime:
        dt = from_iso(iso_or_dt) if isinstance(iso_or_dt, str) else iso_or_dt
        return dt.astimezone(self.tz)

    def clock(self, dt: datetime) -> str:
        return dt.strftime("%I:%M %p").lstrip("0").lower()

    def dayname(self, d: date) -> str:
        today = self.local(self.now).date()
        if d == today:
            return "Today"
        if d == today - timedelta(days=1):
            return "Yesterday"
        return self.longdate(d)

    def longdate(self, d: date) -> str:
        return f"{d.strftime('%A, %B')} {d.day}"

    def stamp(self, dt: datetime) -> str:
        """'today at 4:17 am', 'yesterday at ...', or 'Tuesday, October 28 at ...'."""
        day = self.dayname(dt.date())
        return f"{day.lower() if day in ('Today', 'Yesterday') else day} at {self.clock(dt)}"

    # --- view models ---

    def entry(self, e: Event) -> Entry:
        sources = e.latest_by_outlet()
        regions, label = _coverage([a.outlet for a in sources], self.region_of)
        return Entry(
            event=e,
            story=self.stories.get(e.story_id),
            sources=sources,
            regions=regions,
            coverage_label=label,
            weight=_weight(len(sources)),
            when=self.local(e.first_seen),
        )

    def story_card(self, s: Story) -> StoryCard:
        evs = [self.events[eid] for eid in s.event_ids if eid in self.events]
        outlets = list(dict.fromkeys(o for e in evs for o in e.outlets))
        regions, label = _coverage(outlets, self.region_of)
        topics = Counter(e.topic for e in evs)
        return StoryCard(
            story=s,
            regions=regions,
            coverage_label=label,
            topic=topics.most_common(1)[0][0] if topics else "world",
            single=max((len(e.outlets) for e in evs), default=0) < config.MIN_OUTLETS_DEFAULT,
            last=self.local(s.last_seen),
            first=self.local(s.first_seen),
        )

    def by_day(self, entries: list[Entry], newest_first: bool) -> list[tuple[date, list[Entry]]]:
        entries = sorted(entries, key=lambda x: (x.event.first_seen, x.event.id), reverse=newest_first)
        days: dict[date, list[Entry]] = {}
        for x in entries:
            days.setdefault(x.when.date(), []).append(x)
        return list(days.items())

    # --- output ---

    def render(self, rel_path: str, template: str, **ctx) -> None:
        depth = rel_path.count("/")
        last_run = self.store.load_runs(1)
        html = self.env.get_template(template).render(
            root="../" * depth,
            title=config.SITE_TITLE,
            topics=config.TOPICS,
            regions=REGIONS,
            updated=self.local(last_run[0]["at"]) if last_run else None,
            failed_feeds=last_run[0]["feeds_failed"] if last_run else [],
            outlet_total=self.outlet_total,
            min_default=config.MIN_OUTLETS_DEFAULT,
            min_choices=config.MIN_OUTLET_CHOICES,
            timezone_name=self.local(self.now).tzname(),
            **ctx,
        )
        path = self.out / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")
        self.pages += 1

    def prepare_out(self) -> None:
        if self.out.exists():
            if any(self.out.iterdir()) and not (self.out / MARKER).exists():
                raise SystemExit(f"refusing to overwrite {self.out}: not a previous build directory")
            shutil.rmtree(self.out)
        self.out.mkdir(parents=True)
        (self.out / MARKER).write_text("generated by python -m pipeline build\n")
        (self.out / ".nojekyll").write_text("")
        shutil.copytree(HERE / "static", self.out / "static")

    def build(self) -> int:
        self.prepare_out()
        all_entries = [self.entry(e) for e in self.events.values()]

        cutoff = self.now - config.TIMELINE_WINDOW
        recent = [x for x in all_entries if from_iso(x.event.first_seen) >= cutoff]
        self.render("index.html", "index.html", days=self.by_day(recent, newest_first=True), page="timeline")

        cards = sorted((self.story_card(s) for s in self.stories.values()), key=lambda c: c.story.last_seen, reverse=True)
        self.render("stories/index.html", "stories.html", cards=cards, page="stories")
        entries_by_story: dict[str, list[Entry]] = {}
        for x in all_entries:
            entries_by_story.setdefault(x.event.story_id, []).append(x)
        for card in cards:
            entries = entries_by_story.get(card.story.id, [])
            self.render(
                f"stories/{card.story.id}.html",
                "story.html",
                card=card,
                days=self.by_day(entries, newest_first=False),
                page="stories",
            )

        today = self.local(self.now).date()
        archive_days = []
        for x in self.by_day(all_entries, newest_first=False):
            day, entries = x
            if (today - day).days >= config.SITE_DAYS:
                continue
            archive_days.append((day, len(entries), sum(not e.single for e in entries)))
            self.render(f"archive/{day.isoformat()}.html", "day.html", day=day, days=[x], page="archive")
        archive_days.reverse()
        self.render("archive/index.html", "archive.html", archive_days=archive_days, page="archive")
        return self.pages


def build(data_dir: Path, out_dir: Path, feeds_file: Path = config.FEEDS_FILE, now: datetime | None = None) -> int:
    return SiteBuilder(data_dir, out_dir, feeds_file, now).build()
