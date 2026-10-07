"""The one data shape that flows through the pipeline: a candidate news item."""

import html
import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlsplit

TRACKING_PARAMS = {"ref", "source", "fbclid", "gclid", "mc_cid", "mc_eid"}


@dataclass
class Candidate:
    kind: str  # "rss", "huggingface" or "hackernews"
    source: str  # label shown in the digest, e.g. "Hacker News" or a feed name
    title: str
    url: str
    published: datetime  # timezone-aware, UTC
    score: int = 0  # HN points or HF upvotes; RSS items have no popularity signal
    summary: str = ""  # paper abstract or feed description, plain text

    @property
    def url_key(self) -> str:
        return canonical_url(self.url)

    @property
    def title_key(self) -> str:
        return normalize_title(self.title)


def canonical_url(url: str) -> str:
    """Reduce a URL to a comparison key: no scheme, www, tracking params, fragment or trailing slash."""
    parts = urlsplit(url.strip())
    host = parts.netloc.lower().removeprefix("www.")
    query = urlencode(
        sorted(
            (name, value)
            for name, value in parse_qsl(parts.query)
            if not name.startswith("utm_") and name not in TRACKING_PARAMS
        )
    )
    key = host + parts.path.rstrip("/")
    return f"{key}?{query}" if query else key


def normalize_title(title: str) -> str:
    """Lowercase a title and collapse punctuation and whitespace so near-identical titles compare equal."""
    return re.sub(r"[\W_]+", " ", title.casefold()).strip()


def clean_text(text: str, limit: int = 1000) -> str:
    """Strip HTML tags and entities, collapse whitespace and cap the length."""
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    return " ".join(text.split())[:limit]
