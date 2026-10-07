"""End-to-end runs with every HTTP response faked."""

import sqlite3

import pytest
import requests

from conftest import NOW
from dailygrad import cli, pipeline, web
from dailygrad.config import Config, Feed
from dailygrad.sources import hackernews, huggingface

FEED = Feed("Lab Blog", "https://lab.example/rss.xml")

RSS_BODY = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>Lab Blog</title>
<item><title>Model X released</title><link>https://lab.example/model-x</link>
<pubDate>Wed, 07 Oct 2026 09:00:00 GMT</pubDate></item>
</channel></rss>"""

HF_BODY = [
    {"paper": {"id": "2610.00001", "title": "Sparse attention", "upvotes": 40,
               "submittedOnDailyAt": "2026-10-07T00:00:00.000Z"}},
]  # fmt: skip

HN_BODY = {
    "hits": [
        {"objectID": "1", "title": "Running LLMs on a laptop", "url": "https://example.com/laptop",
         "points": 300, "created_at_i": int(NOW.timestamp()) - 3600},
        {"objectID": "2", "title": "Model X released", "url": "https://lab.example/model-x?utm_source=hn",
         "points": 500, "created_at_i": int(NOW.timestamp()) - 3600},
    ]
}  # fmt: skip


class FakeResponse:
    def __init__(self, body):
        self.content = body

    def json(self):
        return self.content


@pytest.fixture
def config(tmp_path):
    config = Config(data_dir=str(tmp_path / "data"))
    config.rss.feeds = [FEED]
    return config


@pytest.fixture
def fake_web(monkeypatch):
    """Serve canned responses by URL. Set a value to an exception to make that source fail."""
    responses = {FEED.url: RSS_BODY, huggingface.API_URL: HF_BODY, hackernews.API_URL: HN_BODY}

    def get(url, params=None):
        body = responses[url]
        if isinstance(body, Exception):
            raise body
        return FakeResponse(body)

    monkeypatch.setattr(web, "get", get)
    return responses


def test_run_writes_digest_and_updates_database(config, fake_web):
    digest = pipeline.run(config, now=NOW)

    # The HN link to the lab post is a duplicate of the feed entry, which wins.
    assert "1. [Model X released](https://lab.example/model-x) — Lab Blog" in digest
    assert "[Sparse attention](https://arxiv.org/abs/2610.00001)" in digest
    assert "[Running LLMs on a laptop](https://example.com/laptop)" in digest
    assert digest.count("Model X released") == 1

    (digest_file,) = config.digest_dir.glob("*.md")
    assert digest_file.name == f"{NOW.astimezone().date()}.md"
    assert digest_file.read_text(encoding="utf-8") == digest

    conn = sqlite3.connect(config.db_path)
    assert conn.execute("SELECT COUNT(*) FROM runs").fetchone() == (1,)
    assert conn.execute("SELECT COUNT(*) FROM items WHERE shown_run_id IS NOT NULL").fetchone() == (3,)
    conn.close()


def test_second_run_does_not_repeat_stories(config, fake_web):
    pipeline.run(config, now=NOW)

    assert "No new stories today." in pipeline.run(config, now=NOW)


def test_one_failing_source_does_not_abort_the_run(config, fake_web):
    fake_web[hackernews.API_URL] = requests.ConnectionError("network down")
    fake_web[FEED.url] = b"<html>not a feed"

    digest = pipeline.run(config, now=NOW)

    assert "[Sparse attention]" in digest
    assert "_Sources unavailable this run: Lab Blog, Hacker News._" in digest


def test_disabled_sources_are_not_fetched(config, fake_web):
    config.hackernews.enabled = False
    config.huggingface.enabled = False
    del fake_web[hackernews.API_URL], fake_web[huggingface.API_URL]  # fetching these would raise KeyError

    candidates, failed = pipeline.fetch_all(config)

    assert [c.source for c in candidates] == ["Lab Blog"]
    assert failed == []


def test_cli_run_prints_only_the_digest_to_stdout(tmp_path, fake_web, capsys):
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        f'data_dir = "{(tmp_path / "data").as_posix()}"\n[[rss.feeds]]\nname = "{FEED.name}"\nurl = "{FEED.url}"\n'
    )

    assert cli.main(["run", "--config", str(config_file)]) == 0

    stdout = capsys.readouterr().out
    (digest_file,) = (tmp_path / "data" / "digests").glob("*.md")
    assert stdout == digest_file.read_text(encoding="utf-8")
    assert stdout.startswith("# DailyGrad — ")


def test_cli_reports_config_errors(tmp_path, capsys):
    assert cli.main(["run", "--config", str(tmp_path / "missing.toml")]) == 2
    assert "cannot read config file" in capsys.readouterr().err
