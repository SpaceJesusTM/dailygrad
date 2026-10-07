"""End-to-end runs with every HTTP response, the model and article fetching faked."""

import sqlite3
from datetime import timedelta

import pytest
import requests

from conftest import NOW
from dailygrad import articles, cli, lessons, llm, pipeline, stories, web
from dailygrad.config import Config, Feed
from dailygrad.curriculum import build_schedule, load_curriculum
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
SCHEDULE = build_schedule(load_curriculum())  # the order the shipped curriculum is taught in
NO_LESSON_NOTE = "_No lesson today: the local model request failed. The topic will be used in the next run._"
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


def lesson_text(title):
    return f"A lesson about {title}, written from the curriculum points and long enough to be plausible."


class FakeModel:
    """Stands in for Ollama: picks self.selected, summarises and teaches anything, and counts unloads."""

    def __init__(self):
        self.selected = [3, 1, 2]
        self.error = None  # set to an exception to make every request fail
        self.failing_titles = set()  # summaries of these stories fail
        self.lesson_error = None  # set to an exception to make only the lesson request fail
        self.summary_requests = []
        self.lesson_requests = []
        self.unloads = 0

    def chat_json(self, config, system, prompt, schema, temperature=None):
        if self.error:
            raise self.error
        if schema is stories.SELECTION_SCHEMA:
            return {"selected": self.selected}
        if schema is lessons.LESSON_SCHEMA:
            title = prompt.splitlines()[2].removeprefix("Topic: ")
            self.lesson_requests.append(title)
            if self.lesson_error:
                raise self.lesson_error
            return {"lesson": lesson_text(title)}
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


def day(number):
    """A run time on the given day, counting from 0. Days after the first have no fresh news."""
    return NOW + timedelta(days=number)


def table_count(config, table):
    conn = sqlite3.connect(config.db_path)
    (count,) = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
    conn.close()
    return count


def lesson_rows(config):
    conn = sqlite3.connect(config.db_path)
    rows = conn.execute("SELECT topic_id FROM lessons ORDER BY id").fetchall()
    conn.close()
    return [topic_id for (topic_id,) in rows]


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
    assert model.unloads == 3  # even without news the model is loaded, for the lesson, and unloaded


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


# --- the micro-lesson


def test_digest_ends_with_the_lesson_and_history_records_it(config, fake_web, model, fake_articles):
    digest, model_ok = pipeline.run(config, now=NOW)

    first = SCHEDULE[0]
    assert model_ok
    assert digest.endswith(f"## AI Micro-Lesson\n\n**{first.title}**\n\n{lesson_text(first.title)}\n")
    assert digest.index("## AI News") < digest.index("### 3.") < digest.index("## AI Micro-Lesson")
    assert "Quick recall" not in digest
    assert model.lesson_requests == [first.title]

    conn = sqlite3.connect(config.db_path)
    rows = conn.execute("SELECT run_id, topic_id, lesson, model FROM lessons").fetchall()
    conn.close()
    assert rows == [(1, first.id, lesson_text(first.title), "qwen3.5:4b-q4_K_M")]


def test_each_day_teaches_the_next_topic_and_the_third_asks_a_recall_question(config, fake_web, model, fake_articles):
    digests = [pipeline.run(config, now=day(number))[0] for number in range(4)]

    assert model.lesson_requests == [topic.title for topic in SCHEDULE[:4]]
    assert lesson_rows(config) == [topic.id for topic in SCHEDULE[:4]]
    assert ["**Quick recall:**" in digest for digest in digests] == [False, False, True, False]
    assert digests[2].endswith(f"**Quick recall:** {SCHEDULE[0].question}\n")

    conn = sqlite3.connect(config.db_path)
    assert conn.execute("SELECT run_id, topic_id, question FROM recalls").fetchall() == [
        (3, SCHEDULE[0].id, SCHEDULE[0].question)
    ]
    conn.close()


def test_a_day_without_news_still_gets_a_lesson(config, fake_web, model):
    fake_web[huggingface.API_URL], fake_web[hackernews.API_URL] = [], {"hits": []}
    config.rss.feeds = []

    digest, model_ok = pipeline.run(config, now=NOW)

    assert model_ok
    assert "No new stories today." in digest
    assert f"**{SCHEDULE[0].title}**\n\n{lesson_text(SCHEDULE[0].title)}" in digest
    assert lesson_rows(config) == [SCHEDULE[0].id]
    assert model.unloads == 1


def test_lesson_failure_keeps_the_news_and_does_not_advance_the_curriculum(config, fake_web, model, fake_articles):
    model.lesson_error = llm.LLMError("Ollama did not return valid JSON")

    digest, model_ok = pipeline.run(config, now=NOW)

    assert not model_ok  # reported to the scheduler as a degraded run
    assert digest.count("**What happened:**") == 3  # the news digest is complete
    assert digest.endswith(f"## AI Micro-Lesson\n\n{NO_LESSON_NOTE}\n")
    assert shown_titles(config) == ["Model X released", "Running LLMs on a laptop", "Sparse attention"]
    assert lesson_rows(config) == []
    assert model.unloads == 1

    model.lesson_error = None
    retry, model_ok = pipeline.run(config, now=NOW)

    assert model_ok
    assert f"**{SCHEDULE[0].title}**" in retry  # the same topic is tried again, not skipped
    assert model.lesson_requests == [SCHEDULE[0].title, SCHEDULE[0].title]
    assert lesson_rows(config) == [SCHEDULE[0].id]


def test_recall_schedule_counts_only_lessons_that_were_given(config, fake_web, model, fake_articles):
    pipeline.run(config, now=day(0))
    pipeline.run(config, now=day(1))
    model.lesson_error = llm.LLMError("cannot reach Ollama")
    failed, _ = pipeline.run(config, now=day(2))  # would have been lesson 3
    model.lesson_error = None
    third, _ = pipeline.run(config, now=day(2))

    assert "Quick recall" not in failed
    assert f"**Quick recall:** {SCHEDULE[0].question}" in third
    assert lesson_rows(config) == [topic.id for topic in SCHEDULE[:3]]


# --- one lesson per calendar day


def test_same_day_rerun_shows_the_same_lesson_and_does_not_advance(config, fake_web, model, fake_articles):
    first, _ = pipeline.run(config, now=NOW)
    second, model_ok = pipeline.run(config, now=NOW + timedelta(hours=3))
    third, _ = pipeline.run(config, now=NOW + timedelta(hours=6))

    lesson_section = f"## AI Micro-Lesson\n\n**{SCHEDULE[0].title}**\n\n{lesson_text(SCHEDULE[0].title)}\n"
    assert model_ok
    assert first.endswith(lesson_section) and second.endswith(lesson_section) and third.endswith(lesson_section)
    assert lesson_rows(config) == [SCHEDULE[0].id]  # one lesson recorded, however many runs
    assert model.lesson_requests == [SCHEDULE[0].title]  # and the model was asked for it only once
    assert table_count(config, "runs") == 3


def test_next_calendar_day_advances_normally(config, fake_web, model, fake_articles):
    pipeline.run(config, now=day(0))
    pipeline.run(config, now=day(0))  # a rerun, which must not use up a topic
    tomorrow, _ = pipeline.run(config, now=day(1))
    day_after, _ = pipeline.run(config, now=day(2))

    assert f"**{SCHEDULE[1].title}**" in tomorrow
    assert f"**{SCHEDULE[2].title}**" in day_after
    assert lesson_rows(config) == [topic.id for topic in SCHEDULE[:3]]


def test_failed_lesson_is_retried_on_the_same_day_and_then_kept(config, fake_web, model, fake_articles):
    model.lesson_error = llm.LLMError("cannot reach Ollama")
    failed, failed_ok = pipeline.run(config, now=NOW)
    model.lesson_error = None
    retried, retried_ok = pipeline.run(config, now=NOW)
    rerun, _ = pipeline.run(config, now=NOW)

    assert not failed_ok and NO_LESSON_NOTE in failed
    assert retried_ok and f"**{SCHEDULE[0].title}**" in retried  # the same topic, the same day
    assert f"**{SCHEDULE[0].title}**" in rerun
    assert model.lesson_requests == [SCHEDULE[0].title] * 2  # the failed attempt and the retry, not the rerun
    assert lesson_rows(config) == [SCHEDULE[0].id]


def test_same_day_rerun_does_not_use_up_recall_questions(config, fake_web, model, fake_articles):
    for number in range(3):
        pipeline.run(config, now=day(number))  # the third day's lesson carries a recall question
    rerun, _ = pipeline.run(config, now=day(2))
    for number in range(3, 6):
        last, _ = pipeline.run(config, now=day(number))

    assert rerun.endswith(f"**Quick recall:** {SCHEDULE[0].question}\n")  # the rerun repeats the day's question
    assert "**Quick recall:**" in last
    conn = sqlite3.connect(config.db_path)
    recalls = conn.execute("SELECT run_id, topic_id FROM recalls ORDER BY id").fetchall()
    conn.close()
    # Day 3 (run 3) and day 6 (run 7) only: the rerun (run 4) asked nothing new, and day 6 moved on to the next topic.
    assert recalls == [(3, SCHEDULE[0].id), (7, SCHEDULE[1].id)]
    assert lesson_rows(config) == [topic.id for topic in SCHEDULE[:6]]


def test_same_day_rerun_without_news_makes_no_model_request(config, fake_web, ollama):
    fake_web[huggingface.API_URL], fake_web[hackernews.API_URL] = [], {"hits": []}
    config.rss.feeds = []

    pipeline.run(config, now=NOW)
    digest, model_ok = pipeline.run(config, now=NOW)

    assert model_ok and f"**{SCHEDULE[0].title}**" in digest
    # First run: the lesson, then unload. Rerun: nothing to generate, but the unload is still sent.
    assert ollama.requests == [("chat", "10m"), ("generate", 0), ("generate", 0)]


def test_unavailable_model_gives_neither_summaries_nor_lesson(config, fake_web, model, fake_articles):
    model.error = llm.LLMError("cannot reach Ollama at http://localhost:11434")

    digest, model_ok = pipeline.run(config, now=NOW)

    assert not model_ok
    assert NO_LESSON_NOTE in digest and MODEL_FAILED_NOTE in digest
    assert lesson_rows(config) == [] and shown_titles(config) == []


# --- model cleanup, using the real llm module with requests.post faked


class OllamaServer:
    """Fake Ollama HTTP API. Records each request; chat can be made to blow up, for all or one kind of request."""

    def __init__(self):
        self.requests = []
        self.kinds = []  # what each chat request asked for: "selected", "what_happened" or "lesson"
        self.temperatures = []  # the temperature of each chat request
        self.chat_error = None
        self.lesson_crash = None

    def post(self, url, json=None, timeout=None):
        endpoint = url.removeprefix("http://localhost:11434/api/")
        self.requests.append((endpoint, json.get("keep_alive")))
        if endpoint == "chat":
            kind = next(iter(json["format"]["properties"]))
            self.kinds.append(kind)
            self.temperatures.append(json["options"]["temperature"])
            if self.chat_error:
                raise self.chat_error
            if kind == "lesson" and self.lesson_crash:
                raise self.lesson_crash
            content = (
                '{"selected": [1, 2, 3], "what_happened": "Something.", "why_it_matters": "Reasons.",'
                ' "lesson": "A lesson that is long enough to pass validation, written by the fake server for tests."}'
            )
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

    # Selection, three summaries and the lesson share one model load; a final request unloads it.
    assert ollama.kinds == ["selected", "what_happened", "what_happened", "what_happened", "lesson"]
    assert ollama.requests == [("chat", "10m")] * 5 + [("generate", 0)]
    # Only the lesson is generated at temperature 0; news selection and summaries keep the configured 0.2.
    assert ollama.temperatures == [0.2, 0.2, 0.2, 0.2, 0.0]


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
    assert ollama.kinds == ["selected", "lesson"]  # no summaries after a failed selection; the lesson is still tried
    assert ollama.requests == [("chat", "10m"), ("chat", "10m"), ("generate", 0)]
    assert lesson_rows(config) == []


def test_a_day_without_news_loads_the_model_only_for_the_lesson(config, fake_web, ollama):
    fake_web[huggingface.API_URL], fake_web[hackernews.API_URL] = [], {"hits": []}
    config.rss.feeds = []

    digest, model_ok = pipeline.run(config, now=NOW)

    assert "No new stories today." in digest and model_ok
    assert f"**{SCHEDULE[0].title}**" in digest
    assert ollama.kinds == ["lesson"]
    assert ollama.requests == [("chat", "10m"), ("generate", 0)]
    assert lesson_rows(config) == [SCHEDULE[0].id]


def test_model_is_unloaded_when_lesson_generation_raises(config, fake_web, fake_articles, ollama):
    ollama.lesson_crash = RuntimeError("unexpected crash while writing the lesson")

    with pytest.raises(RuntimeError, match="writing the lesson"):
        pipeline.run(config, now=NOW)

    assert ollama.requests[-2:] == [("chat", "10m"), ("generate", 0)]
    assert lesson_rows(config) == [] and shown_titles(config) == []


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


def test_cli_exits_non_zero_when_only_the_lesson_fails(tmp_path, fake_web, model, fake_articles, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    model.lesson_error = llm.LLMError("Ollama did not return valid JSON")

    assert cli.main(["run"]) == 1

    stdout = capsys.readouterr().out
    assert "**What happened:**" in stdout and NO_LESSON_NOTE in stdout


def test_cli_reports_config_errors(tmp_path, capsys):
    assert cli.main(["run", "--config", str(tmp_path / "missing.toml")]) == 2
    assert "cannot read config file" in capsys.readouterr().err
