"""Language-model-free labels: event headlines, story keywords and story titles."""

import math
import re
import unicodedata
from collections import Counter
from datetime import timedelta

import numpy as np

from .cluster import CentroidIndex
from .models import Article, Event, Story
from .normalize import from_iso

STOPWORDS = set(
    """
    a about above after again against all also amid an and any are as at be because been before being below
    between both but by can could did do does doing down during each few for from further had has have having
    he her here hers him his how i if in into is it its itself just me more most my new no nor not now of off
    on once only or other our out over own same she should so some such than that the their them then there
    these they this those through to too under until up very was we were what when where which while who whom
    why will with would you your yours says say said told tells calls call amid after over could may might
    first last year years day days week weeks month months time news report reports latest live update updates
    video watch people man woman men women world government officials official near least more less big top
    make makes made take takes took get gets got set sets back still well way ways one two three four five
    million billion percent per cent against latest analysis explainer
    """.split()
)

_TOKEN_RE = re.compile(r"[^\W\d_](?:[\w'’\-]*[^\W\d_])?")


def _fold(token: str) -> str:
    """Case- and accent-insensitive key, so Flávio and Flavio count as one term."""
    return "".join(c for c in unicodedata.normalize("NFKD", token.lower()) if not unicodedata.combining(c))


def tokens(text: str) -> list[str]:
    out = []
    for tok in _TOKEN_RE.findall(text):
        tok = re.sub(r"['’]s$", "", tok)
        if (len(tok) >= 3 or tok.isupper()) and tok.lower() not in STOPWORDS:
            out.append(tok)
    return out


def relabel_event(event: Event, members: dict[str, Article], vecs: dict[str, np.ndarray], index: CentroidIndex) -> None:
    """Headline = the member closest to the event centroid (preferring ones with a blurb)."""
    candidates = [members[r.id] for r in event.articles if r.id in members and r.id in vecs]
    if not candidates or event.id not in index.row:
        return
    with_blurb = [a for a in candidates if a.blurb] or candidates
    centroid = index.centroid(event.id)
    best = max(with_blurb, key=lambda a: float(vecs[a.id] @ centroid))
    event.headline, event.blurb, event.headline_article_id = best.title, best.blurb, best.id
    topics = Counter(members[r.id].topic for r in event.articles if r.id in members)
    if topics:
        top = max(topics.values())
        event.topic = "world" if topics.get("world") == top else topics.most_common(1)[0][0]


def story_keywords(titles_by_story: dict[str, list[str]], top_n: int = 4) -> dict[str, list[str]]:
    """Class-based TF-IDF: terms frequent in one story and rare across the rest."""
    counts: dict[str, Counter] = {}
    surface: dict[str, Counter] = {}
    for sid, titles in titles_by_story.items():
        c = Counter()
        for title in titles:
            for tok in tokens(title):
                key = _fold(tok)
                c[key] += 1
                surface.setdefault(key, Counter())[tok] += 1
        counts[sid] = c
    if not counts:
        return {}
    total = Counter()
    for c in counts.values():
        total.update(c)
    avg_words = sum(total.values()) / len(counts) or 1.0

    out = {}
    for sid, c in counts.items():
        scored = sorted(c, key=lambda t: (-c[t] * math.log(1 + avg_words / total[t]), -c[t], t))
        out[sid] = [surface[t].most_common(1)[0][0] for t in scored[:top_n]]
    return out


def relabel_story(story: Story, events: dict[str, Event]) -> None:
    """Title = headline of the most-covered event from the story's last 48 hours."""
    evs = [events[eid] for eid in story.event_ids if eid in events]
    if not evs:
        return
    recent_cutoff = from_iso(story.last_seen) - timedelta(hours=48)
    recent = [e for e in evs if from_iso(e.last_seen) >= recent_cutoff] or evs
    lead = max(recent, key=lambda e: (len(e.outlets), e.last_seen))
    story.title = lead.headline
    story.outlet_count = len({o for e in evs for o in e.outlets})
