"""Text, URL and time normalization for feed items."""

import calendar
import hashlib
import html
import re
import time
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Query parameters that only track where a click came from. Anything else is
# kept, since some sites identify the article itself by query string.
TRACKING_PARAMS = {
    "at_medium", "at_campaign", "at_link_origin", "at_format", "at_ptr_name",
    "cmp", "cmpid", "emc", "fbclid", "gclid", "icid", "mc_cid", "mc_eid",
    "ns_campaign", "ns_fee", "ns_linkname", "ns_mchannel", "ns_source",
    "ocid", "partner", "rss", "smid", "taid", "xtor", "dmcid", "traffic_source",
}

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

# Feed-description noise: sign-up pitches, "continue reading" tails, wire datelines.
_BLURB_NOISE = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"get our [\w ,’']*?(?:email|newsletter)(?:[\w ,]*?podcast)?\.?",
        r"sign up (?:for|to) (?:our|the) [^.]*?newsletter[^.]*\.?",
        r"\bcontinue reading\W*$",
        r"\bread (?:more|the full (?:story|article))\W*$",
        r"the post .{0,200}? appeared first on .*$",
        r"\[(?:\.\.\.|…)\]\s*$",
    )
]
_DATELINE = re.compile(
    r"^(?:[A-Z][a-z]{2,8}\.? \d{1,2},? )?(?:[A-Z][A-Z .\'-]{2,30},?\s*)?"
    r"(?:\((?:Reuters|AP|AFP|Bloomberg|dpa|Xinhua|Yonhap|Kyodo)\)\s*)?[-–—:]\s+"
)


def canonical_url(url: str) -> str:
    """Lowercase scheme/host, drop the fragment and tracking parameters."""
    parts = urlsplit(url.strip())
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in TRACKING_PARAMS
    ]
    scheme = "https" if parts.scheme in ("http", "https") else parts.scheme
    return urlunsplit((scheme, parts.netloc.lower(), parts.path or "/", urlencode(query), ""))


def article_id(url: str) -> str:
    return hashlib.sha1(canonical_url(url).encode()).hexdigest()[:16]


def html_to_text(raw: str | None) -> str:
    if not raw:
        return ""
    text = _TAG_RE.sub(" ", raw)
    return _WS_RE.sub(" ", html.unescape(text)).strip()


def clean_blurb(text: str) -> str:
    for pattern in _BLURB_NOISE:
        text = pattern.sub(" ", text)
    text = _DATELINE.sub("", text.strip(), count=1)
    return _WS_RE.sub(" ", text).strip()


def truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    cut = text[: max_chars - 1]
    space = cut.rfind(" ")
    if space > max_chars // 2:
        cut = cut[:space]
    return cut.rstrip(" ,;:.-–—") + "…"


def struct_to_datetime(value: time.struct_time | None) -> datetime | None:
    """feedparser's *_parsed fields are UTC struct_times."""
    if not value:
        return None
    return datetime.fromtimestamp(calendar.timegm(value), tz=UTC)


def to_iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def from_iso(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def now_utc() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)
