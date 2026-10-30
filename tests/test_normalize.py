from pipeline.normalize import article_id, canonical_url, clean_blurb, html_to_text, truncate


def test_canonical_url_strips_tracking_but_keeps_real_params():
    url = "HTTP://News.Example.com/a/b?id=7&utm_source=rss&at_medium=RSS&smid=x#comments"
    assert canonical_url(url) == "https://news.example.com/a/b?id=7"


def test_article_id_ignores_tracking_variants():
    assert article_id("https://x.com/story?utm_campaign=a") == article_id("https://x.com/story")
    assert article_id("https://x.com/story?id=1") != article_id("https://x.com/story?id=2")


def test_html_to_text():
    assert html_to_text("<p>Fish &amp; <b>chips</b></p>\n\n now") == "Fish & chips now"
    assert html_to_text(None) == ""


def test_clean_blurb_removes_boilerplate_and_datelines():
    assert clean_blurb("BEIJING (Reuters) - China said on Friday") == "China said on Friday"
    assert clean_blurb("Oct 29 (Reuters) - Binance said") == "Binance said"
    assert clean_blurb("KYIV: Strikes paused") == "Strikes paused"
    assert clean_blurb("A court heard Get our breaking news email, free app or daily news podcast claims") == (
        "A court heard claims"
    )
    assert clean_blurb("Results are in. Continue reading...") == "Results are in."


def test_clean_blurb_keeps_ordinary_colons():
    assert clean_blurb("Ukraine: strike kills two") == "Ukraine: strike kills two"


def test_truncate_on_word_boundary():
    text = "one two three four five six seven"
    assert truncate(text, 100) == text
    out = truncate(text, 16)
    assert out.endswith("…") and len(out) <= 16 and not out[:-1].endswith(" ")
