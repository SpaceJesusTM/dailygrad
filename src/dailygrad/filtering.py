"""Deterministic filtering: turn everything the sources returned into a short candidate list."""

import re
import sqlite3
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
        if not passes_source_rules(candidate, config, keywords):
            continue
        kept.append(candidate)

    unseen = [c for c in dedupe(kept) if not db.was_shown(conn, c)]
    return interleave(unseen, config.filter.shortlist_size)


def keyword_pattern(keywords: list[str]) -> re.Pattern | None:
    """Match any keyword as a whole word, allowing a plural 's'. None means no keyword filtering."""
    if not keywords:
        return None
    words = "|".join(re.escape(keyword) for keyword in keywords)
    return re.compile(rf"\b(?:{words})s?\b", re.IGNORECASE)


def passes_source_rules(candidate: Candidate, config: Config, keywords: re.Pattern | None) -> bool:
    """Popularity and topic checks, which differ by source."""
    if candidate.kind == "hackernews":
        # The HN front page covers every topic, so it is the one source that needs keywords.
        on_topic = keywords is None or keywords.search(candidate.title) is not None
        return candidate.score >= config.hackernews.min_points and on_topic
    if candidate.kind == "huggingface":
        return candidate.score >= config.huggingface.min_upvotes
    return True  # RSS feeds are curated and carry no popularity signal


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


def interleave(candidates: list[Candidate], size: int) -> list[Candidate]:
    """Take the best items from each source kind in turn, so no single source fills the shortlist.

    Scores are not comparable across sources (points vs upvotes vs none), so items are
    ranked only within their own kind: by score, then by recency.
    """
    queues: dict[str, list[Candidate]] = {}
    for candidate in candidates:
        queues.setdefault(candidate.kind, []).append(candidate)
    for queue in queues.values():
        queue.sort(key=lambda c: (c.score, c.published), reverse=True)

    shortlist = []
    while len(shortlist) < size and any(queues.values()):
        for queue in queues.values():
            if queue and len(shortlist) < size:
                shortlist.append(queue.pop(0))
    return shortlist
