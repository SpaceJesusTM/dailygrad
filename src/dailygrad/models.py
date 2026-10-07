"""The data shapes that flow through the pipeline: news candidates and stories, curriculum topics and lessons."""

import html
import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlsplit

TRACKING_PARAMS = {"ref", "source", "fbclid", "gclid", "mc_cid", "mc_eid"}
SCORE_UNITS = {"hackernews": "points", "huggingface": "upvotes"}


@dataclass
class Candidate:
    kind: str  # "rss", "huggingface" or "hackernews"
    source: str  # label shown in the digest, e.g. "Hacker News" or a feed name
    title: str
    url: str
    published: datetime  # timezone-aware, UTC
    score: int = 0  # HN points or HF upvotes; RSS items have no popularity signal
    comments: int = 0  # HN comment count
    summary: str = ""  # paper abstract or feed description, plain text

    @property
    def url_key(self) -> str:
        return canonical_url(self.url)

    @property
    def title_key(self) -> str:
        return normalize_title(self.title)

    @property
    def byline(self) -> str:
        """The source plus its popularity signal, e.g. "Hacker News, 312 points"."""
        if self.kind in SCORE_UNITS:
            return f"{self.source}, {self.score} {SCORE_UNITS[self.kind]}"
        return self.source


@dataclass
class Story:
    """A candidate chosen for the digest. The summary fields stay empty if no summary could be written."""

    candidate: Candidate
    what_happened: str = ""
    why_it_matters: str = ""
    evidence: str = ""  # what the summary was written from: "article", "abstract" or "excerpt"
    model_failed: bool = False  # a model request failed, so this story is not recorded as shown


@dataclass(frozen=True)
class Topic:
    """One curriculum entry: vetted source material for a micro-lesson, not the lesson itself."""

    id: str
    track: str
    series: str
    part: int  # position within the series, from 1
    title: str
    points: tuple[str, ...]
    question: str  # interview-style; also asked later as a recall question
    formula: str = ""


@dataclass
class Lesson:
    topic: Topic
    text: str
    recall: Topic | None = None  # an earlier topic whose question is asked alongside this lesson


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
