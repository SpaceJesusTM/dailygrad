"""Configurable RSS/Atom feeds, e.g. official AI-lab blogs."""

from datetime import datetime, timezone

import feedparser

from dailygrad import web
from dailygrad.config import Feed
from dailygrad.models import Candidate, clean_text


def fetch(feed: Feed) -> list[Candidate]:
    # Download through web.get so the request has our timeout and retries, then parse the bytes.
    return parse(feed, web.get(feed.url).content)


def parse(feed: Feed, content: bytes) -> list[Candidate]:
    parsed = feedparser.parse(content)
    if parsed.bozo and not parsed.entries:
        raise ValueError(f"could not parse feed {feed.name}: {parsed.bozo_exception}")

    candidates = []
    for entry in parsed.entries:
        title, link = entry.get("title"), entry.get("link")
        # feedparser normalises dates to UTC struct_time.
        when = entry.get("published_parsed") or entry.get("updated_parsed")
        if not (title and link and when):
            continue
        candidates.append(
            Candidate(
                kind="rss",
                source=feed.name,
                title=clean_text(title),
                url=link,
                published=datetime(*when[:6], tzinfo=timezone.utc),
                summary=clean_text(entry.get("summary") or ""),
            )
        )
    return candidates
