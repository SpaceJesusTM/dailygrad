"""Hacker News front-page stories, via the Algolia HN Search API (one request)."""

from datetime import datetime, timezone

from dailygrad import web
from dailygrad.models import Candidate

API_URL = "https://hn.algolia.com/api/v1/search"
ITEM_URL = "https://news.ycombinator.com/item?id={}"


def fetch() -> list[Candidate]:
    response = web.get(API_URL, params={"tags": "front_page", "hitsPerPage": 50})
    return parse(response.json())


def parse(payload: dict) -> list[Candidate]:
    candidates = []
    for hit in payload["hits"]:
        title, created = hit.get("title"), hit.get("created_at_i")
        if not title or not created:
            continue
        candidates.append(
            Candidate(
                kind="hackernews",
                source="Hacker News",
                title=title.strip(),
                # Ask HN / Show HN text posts have no external URL.
                url=hit.get("url") or ITEM_URL.format(hit["objectID"]),
                published=datetime.fromtimestamp(created, timezone.utc),
                score=hit.get("points") or 0,
            )
        )
    return candidates
