"""End-to-end runs with every HTTP response, the model and article fetching faked."""

import json
import os
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
    config.final_story_count = 3  # the six fixture candidates then leave the model a real choice
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
    assert digest.count("### ") == 3  # the top of the deterministic shortlist, as headlines
    assert "**What happened:**" not in digest
    assert digest.count(MODEL_FAILED_NOTE) == 3
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


# --- five stories by default


def test_digest_has_exactly_five_stories_by_default(config, fake_web, model, fake_articles):
    config.final_story_count = Config().final_story_count
    model.selected = [3, 1, 2, 5, 4]

    digest, model_ok = pipeline.run(config, now=NOW)

    assert Config().final_story_count == 5
    assert model_ok and digest.count("### ") == 5 and digest.count("**What happened:**") == 5
    assert "GPT wrappers considered harmful" not in digest  # the sixth candidate is left for another day
    assert len(shown_titles(config)) == 5


def test_digest_is_topped_up_to_five_when_the_model_picks_fewer(config, fake_web, model, fake_articles):
    config.final_story_count = 5
    model.selected = [3, 1]  # the model stops at two

    digest, _ = pipeline.run(config, now=NOW)

    headings = [line for line in digest.splitlines() if line.startswith("### ")]
    assert [heading.split("[")[1].split("]")[0] for heading in headings] == [
        "Running LLMs on a laptop", "Model X released",  # the model's picks, in its order
        "Sparse attention", "Dense attention", "An AI agent framework",  # then the top of the ranked shortlist
    ]  # fmt: skip
    assert digest.count("**What happened:**") == 5


def test_digest_shows_what_exists_when_fewer_than_five_candidates_are_available(config, fake_web, model, fake_articles):
    config.final_story_count = 5
    fake_web[huggingface.API_URL] = []
    fake_web[hackernews.API_URL] = {"hits": HN_BODY["hits"][:2]}  # two stories, one a duplicate of the feed post

    digest, model_ok = pipeline.run(config, now=NOW)

    assert model_ok and digest.count("### ") == 2
    assert model.summary_requests == ["Model X released", "Running LLMs on a laptop"]  # no selection was needed


# --- output files


def read_latest(config):
    return json.loads(config.latest_json_path.read_text(encoding="utf-8"))


def dated_json(config, when):
    return config.digest_dir / f"{when.astimezone().date()}.json"


def test_latest_markdown_matches_the_dated_digest_and_stdout(config, fake_web, model, fake_articles):
    digest, _ = pipeline.run(config, now=NOW)

    dated = config.digest_dir / f"{NOW.astimezone().date()}.md"
    assert dated.read_text(encoding="utf-8") == digest
    assert config.latest_markdown_path.read_text(encoding="utf-8") == digest
    assert config.latest_markdown_path == config.digest_dir.parent / "latest.md"
    assert sorted(path.name for path in config.digest_dir.parent.iterdir()) == [
        "dailygrad.db", "digests", "latest.json", "latest.md"
    ]  # fmt: skip  (no temporary files are left behind)


def test_latest_json_describes_the_same_digest(config, fake_web, model, fake_articles):
    for number in range(3):
        digest, _ = pipeline.run(config, now=day(number))

    document = read_latest(config)
    today = day(2).astimezone().date().isoformat()
    assert document == {
        "schema_version": 1,
        "run_id": 3,
        "date": today,
        "generated_at": day(2).isoformat(timespec="seconds"),
        "status": "ok",
        "model": "qwen3.5:4b-q4_K_M",
        "stories": [],  # the fixture news is two days old by now
        "failed_sources": [],
        "lesson": {
            "topic_id": SCHEDULE[2].id,
            "title": SCHEDULE[2].title,
            "track": SCHEDULE[2].track,
            "track_name": "Modern architectures, LLMs and inference",
            "series": SCHEDULE[2].series,
            "lesson": lesson_text(SCHEDULE[2].title),
        },
        "recall": {"topic_id": SCHEDULE[0].id, "question": SCHEDULE[0].question},
    }
    assert f"**{SCHEDULE[2].title}**" in digest


def test_latest_json_stories_carry_ids_summaries_and_evidence(config, fake_web, model, fake_articles):
    fake_articles["https://lab.example/model-x"] = requests.ConnectionError("connection reset")

    pipeline.run(config, now=NOW)

    document = read_latest(config)
    assert document["status"] == "ok" and document["recall"] is None
    assert document["stories"] == [
        {
            "id": "example.com/laptop",
            "title": "Running LLMs on a laptop",
            "source": "Hacker News",
            "url": "https://example.com/laptop",
            "what_happened": "Summary of Running LLMs on a laptop.",
            "why_it_matters": "Running LLMs on a laptop matters.",
            "evidence": "article",
            "model_failed": False,
        },
        {  # its article could not be fetched: listed without a summary, which is not a model failure
            "id": "lab.example/model-x",
            "title": "Model X released",
            "source": "Lab Blog",
            "url": "https://lab.example/model-x",
            "what_happened": None,
            "why_it_matters": None,
            "evidence": None,
            "model_failed": False,
        },
        {
            "id": "arxiv.org/abs/2610.00001",
            "title": "Sparse attention",
            "source": "Hugging Face Daily Papers",
            "url": "https://arxiv.org/abs/2610.00001",
            "what_happened": "Summary of Sparse attention.",
            "why_it_matters": "Sparse attention matters.",
            "evidence": "abstract",
            "model_failed": False,
        },
    ]


def test_latest_json_marks_a_degraded_run(config, fake_web, model, fake_articles):
    model.failing_titles = {"Sparse attention"}
    model.lesson_error = llm.LLMError("cannot reach Ollama")
    fake_web[FEED.url] = b"<html>not a feed"

    _, model_ok = pipeline.run(config, now=NOW)

    document = read_latest(config)
    assert not model_ok and document["status"] == "degraded"
    assert document["lesson"] is None and document["recall"] is None
    assert document["failed_sources"] == ["Lab Blog"]
    failed = [story for story in document["stories"] if story["model_failed"]]
    assert [story["title"] for story in failed] == ["Sparse attention"]
    assert failed[0]["what_happened"] is None and failed[0]["evidence"] is None
    assert sum(story["what_happened"] is not None for story in document["stories"]) == 2


def test_only_a_failed_lesson_also_counts_as_degraded(config, fake_web, model, fake_articles):
    model.lesson_error = llm.LLMError("cannot reach Ollama")

    pipeline.run(config, now=NOW)

    document = read_latest(config)
    assert document["status"] == "degraded"
    assert not any(story["model_failed"] for story in document["stories"])


def test_latest_files_follow_the_most_recent_run(config, fake_web, model, fake_articles):
    pipeline.run(config, now=day(0))
    first_json = config.latest_json_path.read_bytes()
    second, _ = pipeline.run(config, now=day(1))

    assert config.latest_markdown_path.read_text(encoding="utf-8") == second
    assert read_latest(config)["date"] == day(1).astimezone().date().isoformat()
    assert len(list(config.digest_dir.glob("*.md"))) == 2  # the dated archive keeps both
    # Each day's dated JSON is the document that was latest.json after that day's run.
    assert dated_json(config, day(0)).read_bytes() == first_json
    assert dated_json(config, day(1)).read_bytes() == config.latest_json_path.read_bytes()
    assert sorted(path.name for path in config.digest_dir.iterdir()) == sorted(
        f"{when.astimezone().date()}.{suffix}" for when in (day(0), day(1)) for suffix in ("json", "md")
    )


def test_run_id_is_the_database_run_and_grows_with_every_run(config, fake_web, model, fake_articles):
    ids = []
    for when in (day(0), day(0), day(1)):  # a same-day rerun is a new run too
        pipeline.run(config, now=when)
        ids.append(read_latest(config)["run_id"])

    conn = sqlite3.connect(config.db_path)
    recorded = [run_id for (run_id,) in conn.execute("SELECT id FROM runs ORDER BY id")]
    conn.close()
    assert ids == recorded == [1, 2, 3]
    assert json.loads(dated_json(config, day(0)).read_text(encoding="utf-8"))["run_id"] == 2  # the day's last run


def test_degraded_run_also_has_a_run_id_and_a_dated_json(config, fake_web, model, fake_articles):
    model.error = llm.LLMError("cannot reach Ollama at http://localhost:11434")

    pipeline.run(config, now=NOW)

    document = read_latest(config)
    assert (document["run_id"], document["status"]) == (1, "degraded")
    assert dated_json(config, NOW).read_bytes() == config.latest_json_path.read_bytes()


def test_a_run_is_not_recorded_if_its_files_cannot_be_written(config, fake_web, model, fake_articles, monkeypatch):
    pipeline.run(config, now=day(0))
    files = (config.latest_json_path, config.latest_markdown_path, dated_json(config, day(0)))
    before = [path.read_bytes() for path in files]
    disk = {"full": True}
    real_fsync = os.fsync

    def fsync(file_descriptor):
        if disk["full"]:
            raise OSError("disk full")
        real_fsync(file_descriptor)

    monkeypatch.setattr(os, "fsync", fsync)
    with pytest.raises(OSError, match="disk full"):
        pipeline.run(config, now=day(1))

    assert table_count(config, "runs") == 1 and lesson_rows(config) == [SCHEDULE[0].id]  # the failed run left no trace
    assert [path.read_bytes() for path in files] == before

    disk["full"] = False
    pipeline.run(config, now=day(1))
    assert read_latest(config)["run_id"] == 2  # no digest ever named the run that was rolled back


def test_a_crashed_run_leaves_the_previous_outputs_untouched(config, fake_web, fake_articles, ollama):
    pipeline.run(config, now=day(0))
    before = (config.latest_markdown_path.read_bytes(), config.latest_json_path.read_bytes())
    ollama.lesson_crash = RuntimeError("unexpected crash while writing the lesson")

    with pytest.raises(RuntimeError):
        pipeline.run(config, now=day(1))

    assert (config.latest_markdown_path.read_bytes(), config.latest_json_path.read_bytes()) == before
    assert dated_json(config, day(0)).read_bytes() == before[1]  # the existing dated JSON is intact
    assert not dated_json(config, day(1)).exists()  # and the crashed run wrote none


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


def test_cli_config_shows_where_files_go_and_what_will_be_used(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config_file = tmp_path / "custom.toml"
    config_file.write_text('data_dir = "out"\nfinal_story_count = 4\n[ollama]\nmodel = "llama3.2:3b"\n')

    assert cli.main(["config", "--config", str(config_file)]) == 0

    shown = capsys.readouterr().out
    base = (tmp_path / "out").resolve()
    for expected in (
        f"Config file:        {config_file.resolve()}",
        f"Database:           {base / 'dailygrad.db'}",
        f"Dated digests:      {base / 'digests' / 'YYYY-MM-DD'}.md and .json",
        f"Latest digest:      {base / 'latest.md'}",
        f"Latest JSON:        {base / 'latest.json'}",
        "Ollama endpoint:    http://localhost:11434",
        "Ollama model:       llama3.2:3b",
        "Stories per digest: 4, chosen from up to 18 candidates",
        "Hugging Face Daily Papers, Hacker News",
    ):
        assert expected in shown
    assert not (tmp_path / "out").exists()  # showing the settings creates nothing


def test_cli_config_without_a_file_reports_the_defaults(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DAILYGRAD_CONFIG", raising=False)

    assert cli.main(["config"]) == 0

    shown = capsys.readouterr().out
    assert "Config file:        none (built-in defaults)" in shown
    assert "Stories per digest: 5, chosen from up to 18 candidates" in shown


def test_cli_version(capsys):
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--version"])

    assert exit_info.value.code == 0
    assert capsys.readouterr().out.startswith("dailygrad 0.")
