"""Deterministic filtering: turn everything the sources returned into a short candidate list."""

import re
import sqlite3
from collections.abc import Callable
from datetime import datetime, timedelta

from dailygrad import db
from dailygrad.config import Config
from dailygrad.models import Candidate


def build_shortlist(
    candidates: list[Candidate], config: Config, conn: sqlite3.Connection, now: datetime
) -> list[Candidate]:
    cutoff = now - timedelta(hours=config.filter.max_age_hours)
    keywords = keyword_pattern(config.filter.keywords)

    kept = []
    for candidate in candidates:
        if not candidate.url.startswith(("http://", "https://")):
            continue
        if candidate.published < cutoff:
            continue
        if not is_popular_enough(candidate, config):
            continue
        kept.append(candidate)

    unseen = [c for c in dedupe(kept) if not db.was_shown(conn, c)]
    return interleave(unseen, config.filter.shortlist_size, rank=lambda c: rank_score(c, config, keywords, now))


def keyword_pattern(keywords: list[str]) -> re.Pattern | None:
    """Match any keyword as a whole word, allowing a plural 's'. None means there are no keywords."""
    if not keywords:
        return None
    words = "|".join(re.escape(keyword) for keyword in keywords)
    return re.compile(rf"\b(?:{words})s?\b", re.IGNORECASE)


def is_popular_enough(candidate: Candidate, config: Config) -> bool:
    """The minimum popularity for a source. RSS feeds are curated and carry no popularity signal."""
    if candidate.kind == "hackernews":
        return candidate.score >= config.hackernews.min_points
    if candidate.kind == "huggingface":
        return candidate.score >= config.huggingface.min_upvotes
    return True


def rank_score(candidate: Candidate, config: Config, keywords: re.Pattern | None, now: datetime) -> float:
    """How strongly a candidate competes for its source's places in the shortlist."""
    if candidate.kind == "hackernews":
        return hacker_news_score(candidate, config, keywords, now)
    return float(candidate.score)


def hacker_news_score(candidate: Candidate, config: Config, keywords: re.Pattern | None, now: datetime) -> float:
    """Rank a Hacker News story by popularity, freshness and whether its title looks like AI.

        score = (points + comments / 2) * freshness * keyword boost

    Freshness falls in a straight line from 1.0 for a new story to 0.5 at the age limit.
    The keyword boost is hackernews.keyword_boost when the title contains a configured
    keyword, and 1 otherwise. The front page covers every topic, so the boost puts AI
    stories first. It is not a gate: a story with no keyword still ranks, and makes the
    shortlist when it is several times as popular as the keyword stories it competes with.
    """
    popularity = candidate.score + candidate.comments / 2
    age = (now - candidate.published) / timedelta(hours=config.filter.max_age_hours)
    freshness = 1 - 0.5 * min(max(age, 0.0), 1.0)
    matches = keywords is not None and keywords.search(candidate.title) is not None
    return popularity * freshness * (config.hackernews.keyword_boost if matches else 1.0)


def dedupe(candidates: list[Candidate]) -> list[Candidate]:
    """Drop items sharing a canonical URL or normalized title. The first occurrence wins."""
    seen_urls, seen_titles, unique = set(), set(), []
    for candidate in candidates:
        if candidate.url_key in seen_urls or candidate.title_key in seen_titles:
            continue
        seen_urls.add(candidate.url_key)
        seen_titles.add(candidate.title_key)
        unique.append(candidate)
    return unique


def interleave(candidates: list[Candidate], size: int, rank: Callable[[Candidate], float]) -> list[Candidate]:
    """Take the best items from each source kind in turn, so no single source fills the shortlist.

    Scores are not comparable across sources (points vs upvotes vs none), so items are
    ranked only within their own kind: by `rank`, then by recency.
    """
    queues: dict[str, list[Candidate]] = {}
    for candidate in candidates:
        queues.setdefault(candidate.kind, []).append(candidate)
    for queue in queues.values():
        queue.sort(key=lambda c: (rank(c), c.published), reverse=True)

    shortlist = []
    while len(shortlist) < size and any(queues.values()):
        for queue in queues.values():
            if queue and len(shortlist) < size:
                shortlist.append(queue.pop(0))
    return shortlist
