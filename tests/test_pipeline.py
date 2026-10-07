"""End-to-end runs with every HTTP response, the model and article fetching faked."""

import sqlite3

import pytest
import requests

from conftest import NOW
from dailygrad import articles, cli, llm, pipeline, stories, web
from dailygrad.config import Config, Feed
from dailygrad.sources import hackernews, huggingface

FEED = Feed("Lab Blog", "https://lab.example/rss.xml")

RSS_BODY = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>Lab Blog</title>
<item><title>Model X released</title><link>https://lab.example/model-x</link>
<pubDate>Wed, 07 Oct 2026 09:00:00 GMT</pubDate></item>
</channel></rss>"""

ABSTRACT = "We study sparse attention in depth. " * 10

HF_BODY = [
    {"paper": {"id": "2610.00001", "title": "Sparse attention", "upvotes": 40, "summary": ABSTRACT,
               "submittedOnDailyAt": "2026-10-07T00:00:00.000Z"}},
    {"paper": {"id": "2610.00002", "title": "Dense attention", "upvotes": 20, "summary": ABSTRACT,
               "submittedOnDailyAt": "2026-10-07T00:00:00.000Z"}},
]  # fmt: skip


def hn_hit(number, title, url, points):
    return {"objectID": str(number), "title": title, "url": url, "points": points,
            "created_at_i": int(NOW.timestamp()) - 3600}  # fmt: skip


HN_BODY = {
    "hits": [
        hn_hit(1, "Running LLMs on a laptop", "https://example.com/laptop", 300),
        hn_hit(2, "Model X released", "https://lab.example/model-x?utm_source=hn", 500),
        hn_hit(3, "An AI agent framework", "https://example.com/agents", 200),
        hn_hit(4, "GPT wrappers considered harmful", "https://example.com/wrappers", 100),
    ]
}

# After filtering, the shortlist is, in order:
#   1 Model X released (Lab Blog)   2 Sparse attention   3 Running LLMs on a laptop
#   4 Dense attention               5 An AI agent framework   6 GPT wrappers considered harmful
ARTICLE = "This article explains the topic at length. " * 10
MODEL_FAILED_NOTE = "_Not summarised: the local model request failed. This story may return in a later digest._"


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
    """Serve canned source responses by URL. Set a value to an exception to make that source fail."""
    responses = {FEED.url: RSS_BODY, huggingface.API_URL: HF_BODY, hackernews.API_URL: HN_BODY}

    def get(url, params=None):
        body = responses[url]
        if isinstance(body, Exception):
            raise body
        return FakeResponse(body)

    monkeypatch.setattr(web, "get", get)
    return responses


class FakeModel:
    """Stands in for Ollama: picks self.selected, summarises anything, and counts unloads."""

    def __init__(self):
        self.selected = [3, 1, 2]
        self.error = None  # set to an exception to make every request fail
        self.failing_titles = set()  # summaries of these stories fail
        self.summary_requests = []
        self.unloads = 0

    def chat_json(self, config, system, prompt, schema):
        if self.error:
            raise self.error
        if schema is stories.SELECTION_SCHEMA:
            return {"selected": self.selected}
        title = prompt.splitlines()[0].removeprefix("Title: ")
        self.summary_requests.append(title)
        if title in self.failing_titles:
            raise llm.LLMError("Ollama did not return valid JSON")
        return {"what_happened": f"Summary of {title}.", "why_it_matters": f"{title} matters."}

    def unload(self, config):
        self.unloads += 1


@pytest.fixture
def model(monkeypatch):
    model = FakeModel()
    monkeypatch.setattr(llm, "chat_json", model.chat_json)
    monkeypatch.setattr(llm, "unload", model.unload)
    return model


@pytest.fixture
def fake_articles(monkeypatch):
    """Every article fetch succeeds unless its URL is mapped to an exception here."""
    failures = {}

    def fetch_article_text(url):
        if url in failures:
            raise failures[url]
        return ARTICLE

    monkeypatch.setattr(articles, "fetch_article_text", fetch_article_text)
    return failures


def shown_titles(config):
    conn = sqlite3.connect(config.db_path)
    rows = conn.execute("SELECT title FROM items WHERE shown_run_id IS NOT NULL ORDER BY title").fetchall()
    conn.close()
    return [title for (title,) in rows]


def test_run_writes_a_summarised_digest_of_the_selected_stories(config, fake_web, model, fake_articles):
    digest, model_ok = pipeline.run(config, now=NOW)

    assert model_ok

    # The model's order is kept. The HN link to the lab post was a duplicate of the feed entry.
    assert digest.index("### 1. [Running LLMs on a laptop](https://example.com/laptop)") < digest.index(
        "### 2. [Model X released](https://lab.example/model-x)"
    ) < digest.index("### 3. [Sparse attention](https://arxiv.org/abs/2610.00001)")
    assert "**What happened:** Summary of Running LLMs on a laptop." in digest
    assert "**Why it matters:** Sparse attention matters." in digest
    assert digest.count("### ") == 3
    assert "Dense attention" not in digest and "agent framework" not in digest

    (digest_file,) = config.digest_dir.glob("*.md")
    assert digest_file.name == f"{NOW.astimezone().date()}.md"
    assert digest_file.read_text(encoding="utf-8") == digest
    assert model.unloads == 1


def test_run_records_seen_shown_and_summaries(config, fake_web, model, fake_articles):
    pipeline.run(config, now=NOW)

    assert shown_titles(config) == ["Model X released", "Running LLMs on a laptop", "Sparse attention"]
    conn = sqlite3.connect(config.db_path)
    assert conn.execute("SELECT COUNT(*) FROM runs").fetchone() == (1,)
    assert conn.execute("SELECT COUNT(*) FROM items").fetchone() == (6,)  # the whole shortlist was seen
    summaries = conn.execute(
        "SELECT items.title, what_happened, evidence, model FROM summaries"
        " JOIN items ON items.id = summaries.item_id ORDER BY items.title"
    ).fetchall()
    conn.close()
    assert summaries == [
        ("Model X released", "Summary of Model X released.", "article", "qwen3.5:4b-q4_K_M"),
        ("Running LLMs on a laptop", "Summary of Running LLMs on a laptop.", "article", "qwen3.5:4b-q4_K_M"),
        ("Sparse attention", "Summary of Sparse attention.", "abstract", "qwen3.5:4b-q4_K_M"),
    ]


def test_second_run_offers_only_stories_not_yet_shown(config, fake_web, model, fake_articles):
    pipeline.run(config, now=NOW)

    second, _ = pipeline.run(config, now=NOW)  # three candidates are left, so all are taken

    assert second.count("### ") == 3
    for title in ("Dense attention", "An AI agent framework", "GPT wrappers considered harmful"):
        assert title in second
    third, model_ok = pipeline.run(config, now=NOW)
    assert "No new stories today." in third
    assert model_ok  # an empty digest is not a model failure
    assert model.unloads == 2  # the third run had no candidates, so the model was never loaded


def test_article_failure_degrades_only_that_story(config, fake_web, model, fake_articles):
    fake_articles["https://example.com/laptop"] = requests.ConnectionError("connection reset")

    digest, model_ok = pipeline.run(config, now=NOW)

    assert digest.count("### ") == 3
    assert "[Running LLMs on a laptop]" in digest
    assert "Summary of Running LLMs on a laptop." not in digest
    assert "Summary of Model X released." in digest and "Summary of Sparse attention." in digest
    assert model.summary_requests == ["Model X released", "Sparse attention"]
    # An unreachable article is not a model failure: the run succeeds and the story counts as shown.
    assert model_ok and MODEL_FAILED_NOTE not in digest
    assert "Running LLMs on a laptop" in shown_titles(config)


def test_unavailable_model_gives_a_degraded_digest_and_consumes_nothing(config, fake_web, model, fake_articles):
    model.error = llm.LLMError("cannot reach Ollama at http://localhost:11434")

    digest, model_ok = pipeline.run(config, now=NOW)

    assert not model_ok
    assert digest.count("### ") == 5  # the top of the deterministic shortlist, as headlines
    assert "**What happened:**" not in digest
    assert digest.count(MODEL_FAILED_NOTE) == 5
    (digest_file,) = config.digest_dir.glob("*.md")
    assert digest_file.read_text(encoding="utf-8") == digest  # the degraded digest is still saved
    assert shown_titles(config) == []
    assert model.unloads == 1


def test_stories_from_a_failed_run_are_offered_again_once_the_model_works(config, fake_web, model, fake_articles):
    model.error = llm.LLMError("cannot reach Ollama at http://localhost:11434")
    pipeline.run(config, now=NOW)

    model.error = None
    digest, model_ok = pipeline.run(config, now=NOW)

    assert model_ok
    assert "**What happened:** Summary of Running LLMs on a laptop." in digest
    assert shown_titles(config) == ["Model X released", "Running LLMs on a laptop", "Sparse attention"]


def test_a_failed_summary_is_not_consumed_but_the_other_stories_are(config, fake_web, model, fake_articles):
    model.failing_titles = {"Model X released"}

    digest, model_ok = pipeline.run(config, now=NOW)

    assert not model_ok
    assert digest.count("### ") == 3 and digest.count(MODEL_FAILED_NOTE) == 1
    assert "Summary of Running LLMs on a laptop." in digest and "Summary of Sparse attention." in digest
    assert shown_titles(config) == ["Running LLMs on a laptop", "Sparse attention"]

    model.failing_titles = set()
    retry, model_ok = pipeline.run(config, now=NOW)

    assert model_ok
    assert "**What happened:** Summary of Model X released." in retry
    assert "Running LLMs on a laptop" not in retry  # already shown, not repeated


def test_one_failing_source_does_not_abort_the_run(config, fake_web, model, fake_articles):
    fake_web[hackernews.API_URL] = requests.ConnectionError("network down")
    fake_web[FEED.url] = b"<html>not a feed"

    digest, model_ok = pipeline.run(config, now=NOW)

    assert model_ok  # a failed source is reported in the digest, not as a model failure

    assert "[Sparse attention]" in digest and "[Dense attention]" in digest
    assert "_Sources unavailable this run: Lab Blog, Hacker News._" in digest


def test_disabled_sources_are_not_fetched(config, fake_web):
    config.hackernews.enabled = False
    config.huggingface.enabled = False
    del fake_web[hackernews.API_URL], fake_web[huggingface.API_URL]  # fetching these would raise KeyError

    candidates, failed = pipeline.fetch_all(config)

    assert [c.source for c in candidates] == ["Lab Blog"]
    assert failed == []


# --- model cleanup, using the real llm module with requests.post faked


class OllamaServer:
    """Fake Ollama HTTP API. Records the endpoint of each request; chat can be made to blow up."""

    def __init__(self):
        self.requests = []
        self.chat_error = None

    def post(self, url, json=None, timeout=None):
        endpoint = url.removeprefix("http://localhost:11434/api/")
        self.requests.append((endpoint, json.get("keep_alive")))
        if endpoint == "chat":
            if self.chat_error:
                raise self.chat_error
            content = '{"selected": [1, 2, 3], "what_happened": "Something.", "why_it_matters": "Reasons."}'
            return FakeOllamaResponse({"message": {"content": content}})
        return FakeOllamaResponse({"done_reason": "unload"})


class FakeOllamaResponse:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload

    def raise_for_status(self):
        pass


@pytest.fixture
def ollama(monkeypatch):
    server = OllamaServer()
    monkeypatch.setattr(requests, "post", server.post)
    return server


def test_model_stays_loaded_during_the_batch_and_is_unloaded_last(config, fake_web, fake_articles, ollama):
    pipeline.run(config, now=NOW)

    # One selection and three summaries keep the model alive; a final request unloads it.
    assert ollama.requests == [("chat", "10m")] * 4 + [("generate", 0)]


def test_model_is_unloaded_when_generation_raises(config, fake_web, fake_articles, ollama):
    ollama.chat_error = RuntimeError("unexpected crash inside the run")

    with pytest.raises(RuntimeError, match="unexpected crash"):
        pipeline.run(config, now=NOW)

    assert ollama.requests == [("chat", "10m"), ("generate", 0)]
    assert not list(config.digest_dir.glob("*.md"))  # nothing was written or recorded
    assert shown_titles(config) == []


def test_model_is_unloaded_when_ollama_requests_fail(config, fake_web, fake_articles, ollama):
    ollama.chat_error = requests.Timeout("read timed out")

    _, model_ok = pipeline.run(config, now=NOW)

    assert not model_ok
    assert ollama.requests == [("chat", "10m"), ("generate", 0)]


def test_model_is_not_touched_when_there_are_no_candidates(config, fake_web, ollama):
    fake_web[FEED.url], fake_web[huggingface.API_URL], fake_web[hackernews.API_URL] = RSS_BODY, [], {"hits": []}
    config.rss.feeds = []

    digest, model_ok = pipeline.run(config, now=NOW)

    assert "No new stories today." in digest and model_ok
    assert ollama.requests == []


# --- CLI


def test_cli_run_prints_only_the_digest_to_stdout(tmp_path, fake_web, model, fake_articles, capsys):
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        f'data_dir = "{(tmp_path / "data").as_posix()}"\n[[rss.feeds]]\nname = "{FEED.name}"\nurl = "{FEED.url}"\n'
    )

    assert cli.main(["run", "--config", str(config_file)]) == 0

    stdout = capsys.readouterr().out
    (digest_file,) = (tmp_path / "data" / "digests").glob("*.md")
    assert stdout == digest_file.read_text(encoding="utf-8")
    assert stdout.startswith("# DailyGrad — ")


def test_cli_exits_non_zero_but_still_prints_the_digest_when_the_model_fails(
    tmp_path, fake_web, model, fake_articles, capsys, monkeypatch
):
    monkeypatch.chdir(tmp_path)  # no config file: the digest goes to ./data
    model.error = llm.LLMError("cannot reach Ollama at http://localhost:11434")

    assert cli.main(["run"]) == 1

    stdout = capsys.readouterr().out
    assert stdout.startswith("# DailyGrad — ") and MODEL_FAILED_NOTE in stdout
    assert list((tmp_path / "data" / "digests").glob("*.md"))


def test_cli_reports_config_errors(tmp_path, capsys):
    assert cli.main(["run", "--config", str(tmp_path / "missing.toml")]) == 2
    assert "cannot read config file" in capsys.readouterr().err
