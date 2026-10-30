"""Records persisted in the data directory."""

from dataclasses import asdict, dataclass, field


@dataclass
class Article:
    id: str
    url: str
    outlet: str
    region: str
    topic: str
    title: str
    blurb: str
    published_at: str
    fetched_at: str
    event_id: str | None = None

    @property
    def embed_text(self) -> str:
        """What gets embedded for clustering: the headline alone (see config)."""
        return self.title

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ArticleRef:
    """The slice of an article an event keeps so pages render without the raw log."""

    id: str
    url: str
    outlet: str
    title: str
    published_at: str

    @classmethod
    def of(cls, a: Article) -> "ArticleRef":
        return cls(a.id, a.url, a.outlet, a.title, a.published_at)


@dataclass
class Event:
    """One development in a story: every outlet's article about the same thing."""

    id: str
    story_id: str
    first_seen: str
    last_seen: str
    topic: str
    headline: str
    blurb: str
    headline_article_id: str
    articles: list[ArticleRef] = field(default_factory=list)
    summary: str | None = None

    @property
    def outlets(self) -> list[str]:
        """Distinct outlets, in the order they first covered the event."""
        return list(dict.fromkeys(a.outlet for a in sorted(self.articles, key=lambda a: a.published_at)))

    def latest_by_outlet(self) -> list[ArticleRef]:
        """One link per outlet (its most recent article), earliest outlet first."""
        latest: dict[str, ArticleRef] = {}
        for a in sorted(self.articles, key=lambda a: a.published_at):
            latest[a.outlet] = a
        first = {o: i for i, o in enumerate(self.outlets)}
        return sorted(latest.values(), key=lambda a: first[a.outlet])

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Event":
        return cls(**{**d, "articles": [ArticleRef(**a) for a in d["articles"]]})


@dataclass
class Story:
    """An ongoing topic: a chain of related events."""

    id: str
    first_seen: str
    last_seen: str
    event_ids: list[str] = field(default_factory=list)
    title: str = ""
    keywords: list[str] = field(default_factory=list)
    outlet_count: int = 0
    summary: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Story":
        return cls(**d)
