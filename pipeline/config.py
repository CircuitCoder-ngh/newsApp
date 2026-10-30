"""Paths, time windows and clustering thresholds. Everything tunable lives here."""

from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FEEDS_FILE = ROOT / "feeds.yaml"
DEFAULT_DATA_DIR = ROOT / "data"
DEFAULT_SITE_DIR = ROOT / "_site"
DEFAULT_CACHE_DIR = ROOT / ".cache"

USER_AGENT = "news-timeline/0.1 (+https://github.com/CircuitCoder-ngh/newsApp; headlines and links only)"
FETCH_TIMEOUT_SECONDS = 20
FETCH_CONCURRENCY = 10

TOPICS = {
    "world": "World",
    "business": "Business",
    "science": "Science, Tech & Health",
}

# Ingest
MAX_ARTICLE_AGE = timedelta(hours=48)  # ignore feed items older than this
BLURB_MAX_CHARS = 280
ARTICLE_RETENTION = timedelta(days=30)  # raw article logs older than this are deleted

# Embedding
EMBED_MODEL = "BAAI/bge-small-en-v1.5"
EMBED_WINDOW = timedelta(days=7)  # articles re-embedded (or read from cache) each run

# Clustering. Headlines (titles only; blurbs vary too much between outlets) are
# compared by average-link: the mean cosine similarity to an event's or story's
# articles, which keeps broad clusters from snowballing. Tuned on two days of
# real coverage: same-event headline pairs score ~0.76-0.97, same-story pairs
# ~0.52-0.70, unrelated pairs ~0.33-0.50.
EVENT_SIM = 0.75  # article joins an event at or above this
STORY_SIM = 0.60  # new event joins a story at or above this
EVENT_GAP = timedelta(hours=18)  # event stops accepting articles after this much silence
EVENT_MAX_SPAN = timedelta(hours=36)  # ...or once it has run this long
STORY_GAP = timedelta(days=7)  # story stops accepting events after this much silence
STORY_CENTROID_ARTICLES = 40  # story matching uses only its latest N articles, so it follows drift

# Housekeeping
STORY_ARCHIVE_AFTER = timedelta(days=30)  # inactive stories move to archive/
RUN_LOG_KEEP = 500  # lines kept in runs.jsonl

# Site
SITE_TITLE = "Worldline"
SITE_TIMEZONE = "America/New_York"  # all times on the site are shown in this zone
TIMELINE_WINDOW = timedelta(hours=48)  # world timeline on the home page
SITE_DAYS = 30  # number of daily archive pages rendered
MIN_OUTLETS_DEFAULT = 2  # events with fewer outlets are hidden until toggled on
