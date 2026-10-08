"""Configurable RSS/Atom feeds, e.g. official AI-lab blogs."""

import logging
from datetime import datetime, timezone
from urllib.parse import urlsplit

import feedparser

from dailygrad import articles, web
from dailygrad.config import Feed
from dailygrad.models import Candidate, clean_text

log = logging.getLogger(__name__)

# Feeds are served under many types; a static file host sends text/plain.
FEED_TYPES = ("application/rss+xml", "application/atom+xml", "application/xml", "text/xml", "text/plain")


def fetch(feed: Feed) -> list[Candidate]:
    if feed.link_hosts:
        # A third-party feed is downloaded as cautiously as an article: checked redirects, capped size.
        return parse(feed, articles.download(feed.url, FEED_TYPES))
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
        if feed.link_hosts and not _links_to(link, feed.link_hosts):
            log.warning("feed %s: ignored an entry linking outside %s", feed.name, ", ".join(feed.link_hosts))
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


def _links_to(link: str, hosts: list[str]) -> bool:
    """Whether `link` is an https URL on exactly one of `hosts`."""
    try:
        parts = urlsplit(link)
        return parts.scheme == "https" and parts.hostname in hosts
    except ValueError:  # e.g. a malformed IPv6 host
        return False
