from datetime import datetime, timedelta, timezone

import pytest

from dailygrad import db, web
from dailygrad.models import Candidate

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Tests must never reach the internet. Tests that need responses replace web.get themselves."""

    def blocked(url, params=None):
        raise AssertionError(f"test tried to fetch {url}")

    monkeypatch.setattr(web, "get", blocked)


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "test.db")
    yield connection
    connection.close()


@pytest.fixture
def make_candidate():
    def make(title="A new LLM", url=None, kind="hackernews", source="Hacker News", score=100, age_hours=1):
        return Candidate(
            kind=kind,
            source=source,
            title=title,
            url=url or f"https://example.com/{title.replace(' ', '-')}",
            published=NOW - timedelta(hours=age_hours),
            score=score,
        )

    return make
