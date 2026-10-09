"""The data shapes that flow through the pipeline: news candidates and stories, curriculum topics and lessons,
and LeetCode problems and exercises."""

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


@dataclass(frozen=True)
class Problem:
    """One catalog entry: a LeetCode problem with practice material written for DailyGrad.

    The fields from `hints` on are for hints, feedback and review. A digest shows none of them
    but the one hint. Its JSON also carries the approach, the complexities and the edge cases as
    `reference_solution`, for a program that tutors; the Markdown never does.
    """

    id: str  # LeetCode's slug: permanent, and what history refers to
    number: int  # LeetCode's problem number
    title: str
    difficulty: str  # "easy", "medium" or "hard"
    category: str
    tracks: tuple[str, ...]  # every source that lists the problem
    statement: str
    example_input: str
    example_output: str
    constraints: tuple[str, ...]
    hints: tuple[str, ...]  # gentlest first; none gives the whole solution
    spoilers: tuple[str, ...]  # words that would give the approach away in a hint
    approach: str  # the reference approach
    time: str
    space: str
    edge_cases: tuple[str, ...]
    premium: bool = False  # on LeetCode the full problem needs a subscription

    @property
    def url(self) -> str:
        return f"https://leetcode.com/problems/{self.id}/"


@dataclass(frozen=True)
class Source:
    """Where a LeetCode track's problem list came from. Provenance only: a run fetches nothing from `url`."""

    id: str  # the track ID
    name: str
    kind: str  # "curriculum", or "company" for a company's list published by a third party
    publisher: str
    url: str
    retrieved: str  # the day the list was read, YYYY-MM-DD
    problems: int  # how many problems the list held that day

    @property
    def credit(self) -> str:
        """How a digest names the source. A company tag is a third party's claim, and is credited to it."""
        return self.name if self.kind == "curriculum" else f"{self.name} ({self.publisher} tag)"


@dataclass
class Exercise:
    """A problem assigned to a day: the track whose turn it was, and the hint written for it."""

    problem: Problem
    track: str
    sources: tuple[Source, ...]  # every source that lists the problem
    review: bool = False  # the problem had been shown before
    hint: str = ""  # empty until one is written; shown only while hints are on
    hint_source: str = ""  # "model" or "catalog"
    hints_on: bool = True
    assignment_id: int | None = None  # its row in leetcode_assignments, once recorded

    @property
    def shown_hint(self) -> str:
        return self.hint if self.hints_on else ""


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
