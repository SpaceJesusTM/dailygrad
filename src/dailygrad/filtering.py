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
    by_kind = {kind: [c for c in unseen if c.kind == kind] for kind in ("rss", "huggingface", "hackernews")}

    # Each kind of source has its own maximum. Places it cannot fill stay empty: they are not given to another kind.
    posts = balance_feeds(by_kind["rss"], config.rss.max_per_feed)[: config.rss.max_candidates]
    papers = ranked(by_kind["huggingface"], lambda c: c.score)[: config.huggingface.max_candidates]
    stories = ranked(by_kind["hackernews"], lambda c: hacker_news_score(c, config, keywords, now))
    return interleave([posts, papers, stories[: config.hackernews.max_candidates]], config.filter.shortlist_size)


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


def ranked(candidates: list[Candidate], rank: Callable[[Candidate], float]) -> list[Candidate]:
    """Best first: by `rank`, then by recency."""
    return sorted(candidates, key=lambda c: (rank(c), c.published), reverse=True)


def balance_feeds(posts: list[Candidate], per_feed: int) -> list[Candidate]:
    """Order RSS posts so that no feed crowds out the others, keeping at most `per_feed` from each.

    Feeds carry no popularity signal, so posts are ranked by recency, in rounds: first every
    feed's newest post, then every feed's second newest, and so on. Within a round the newest
    post comes first; posts published at the same moment go by feed name, then URL, so the
    result never depends on the order the feeds were fetched in. A feed with nothing recent
    simply has no post in the round.
    """

    def newest_first(candidates: list[Candidate]) -> list[Candidate]:
        return sorted(candidates, key=lambda c: (-c.published.timestamp(), c.source, c.url))

    feeds: dict[str, list[Candidate]] = {}
    for post in newest_first(posts):
        feeds.setdefault(post.source, []).append(post)

    balanced = []
    for turn in range(per_feed):
        balanced += newest_first([feed[turn] for feed in feeds.values() if len(feed) > turn])
    return balanced


def interleave(queues: list[list[Candidate]], size: int) -> list[Candidate]:
    """Take the next item from each queue in turn, up to `size` items, so the top of the shortlist mixes the sources.

    Scores are not comparable across sources (points vs upvotes vs none), so each queue
    arrives ranked in its own way and only the turn-taking decides the overall order.
    """
    queues = [list(queue) for queue in queues]
    shortlist = []
    while len(shortlist) < size and any(queues):
        for queue in queues:
            if queue and len(shortlist) < size:
                shortlist.append(queue.pop(0))
    return shortlist
