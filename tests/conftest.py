import socket
from datetime import datetime, timedelta, timezone

import pytest
import requests

from dailygrad import db
from dailygrad.models import Candidate

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Tests must never reach the internet, Ollama included. Tests that need responses fake them."""

    def blocked(*args, **kwargs):
        raise AssertionError("test tried to use the network")

    monkeypatch.setattr(requests.Session, "request", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "test.db")
    yield connection
    connection.close()


@pytest.fixture
def make_candidate():
    def make(
        title="A new LLM", url=None, kind="hackernews", source="Hacker News", score=100, age_hours=1, summary="",
        comments=0,
    ):  # fmt: skip
        return Candidate(
            kind=kind,
            source=source,
            title=title,
            url=url or f"https://example.com/{title.replace(' ', '-')}",
            published=NOW - timedelta(hours=age_hours),
            score=score,
            summary=summary,
            comments=comments,
        )

    return make
