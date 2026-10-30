import numpy as np

from pipeline.cluster import CentroidIndex
from pipeline.label import relabel_event, relabel_story, story_keywords, tokens
from pipeline.models import Article, ArticleRef, Event, Story


def test_tokens_keep_acronyms_and_accents_drop_stopwords():
    assert tokens("Flávio Bolsonaro's US exit says EU") == ["Flávio", "Bolsonaro", "US", "exit", "EU"]


def test_story_keywords_are_distinctive_and_accent_insensitive():
    keywords = story_keywords(
        {
            "a": ["Flávio Bolsonaro lands in Miami", "Flavio Bolsonaro flees Brazil", "Brazil reacts"],
            "b": ["Lagarde to quit ECB early", "ECB head Lagarde steps down", "Brazil trade data"],
        }
    )
    assert keywords["a"][:2] == ["Bolsonaro", "Flávio"]
    assert set(keywords["b"][:2]) == {"ECB", "Lagarde"}


def ref(aid: str, outlet: str, when: str) -> ArticleRef:
    return ArticleRef(aid, f"https://x.com/{aid}", outlet, f"title {aid}", when)


def test_relabel_story_uses_most_covered_recent_event():
    old_big = Event("e1", "s", "2026-10-25T00:00:00Z", "2026-10-25T01:00:00Z", "world", "Old big", "", "a",
                    [ref("a", "A", "2026-10-25T00:00:00Z"), ref("b", "B", "2026-10-25T00:00:00Z"),
                     ref("c", "C", "2026-10-25T00:00:00Z")])
    new_wide = Event("e2", "s", "2026-10-29T00:00:00Z", "2026-10-29T02:00:00Z", "world", "New wide", "", "d",
                     [ref("d", "A", "2026-10-29T00:00:00Z"), ref("e", "B", "2026-10-29T01:00:00Z")])
    new_narrow = Event("e3", "s", "2026-10-29T03:00:00Z", "2026-10-29T03:00:00Z", "world", "New narrow", "", "f",
                       [ref("f", "D", "2026-10-29T03:00:00Z")])
    story = Story("s", "2026-10-25T00:00:00Z", "2026-10-29T03:00:00Z", ["e1", "e2", "e3"])
    relabel_story(story, {e.id: e for e in (old_big, new_wide, new_narrow)})
    assert story.title == "New wide"
    assert story.outlet_count == 4


def test_relabel_event_picks_central_member_with_blurb():
    def article(aid, title, blurb, topic):
        return Article(aid, "u", "A", "Europe", topic, title, blurb, "2026-10-29T00:00:00Z", "2026-10-29T00:00:00Z")

    members = {
        "x": article("x", "Central but no blurb", "", "world"),
        "y": article("y", "Near centre", "Has a blurb", "business"),
        "z": article("z", "Outlier", "Also a blurb", "business"),
    }
    vecs = {"x": np.array([1.0, 0, 0]), "y": np.array([0.9, 0.436, 0]), "z": np.array([0, 0, 1.0])}
    index = CentroidIndex(3)
    for v in vecs.values():
        index.add("e", v.astype(np.float32), 0, 0)
    event = Event("e", "s", "t", "t", "world", "", "", "", [ref(k, "A", "t") for k in vecs])
    relabel_event(event, members, vecs, index)
    assert (event.headline, event.blurb, event.headline_article_id) == ("Near centre", "Has a blurb", "y")
    assert event.topic == "business"
