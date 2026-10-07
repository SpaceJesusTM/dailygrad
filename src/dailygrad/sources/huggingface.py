"""Hugging Face Daily Papers."""

from datetime import datetime

from dailygrad import web
from dailygrad.models import Candidate, clean_text

API_URL = "https://huggingface.co/api/daily_papers"
# Papers are keyed by arXiv ID. Linking to arXiv lets them deduplicate against HN submissions.
PAPER_URL = "https://arxiv.org/abs/{}"


def fetch() -> list[Candidate]:
    response = web.get(API_URL, params={"limit": 50})
    return parse(response.json())


def parse(payload: list) -> list[Candidate]:
    candidates = []
    for entry in payload:
        paper = entry.get("paper") or {}
        paper_id, title = paper.get("id"), paper.get("title")
        # Prefer the day the paper was featured over its original publication date.
        featured = paper.get("submittedOnDailyAt") or entry.get("publishedAt")
        if not (paper_id and title and featured):
            continue
        candidates.append(
            Candidate(
                kind="huggingface",
                source="Hugging Face Daily Papers",
                title=" ".join(title.split()),
                url=PAPER_URL.format(paper_id),
                published=datetime.fromisoformat(featured),
                score=paper.get("upvotes") or 0,
                summary=clean_text(paper.get("summary") or ""),
            )
        )
    return candidates
