"""`dailygrad repair`: a degraded digest completed with the same stories, as a new revision of its run."""

import json
import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest

from conftest import NOW
from dailygrad import cli, db, history, llm, pipeline, render, repair, stories, web
from dailygrad.config import Config
from dailygrad.models import Candidate, Story
from test_leetcode import Tutor
from test_pipeline import FEED, RSS_BODY, SCHEDULE, day, fake_articles, fake_web, lesson_text, read_latest  # noqa: F401 (fixtures)

FAILING = {"Model X released", "Dense attention", "An AI agent framework"}  # stories 2, 4 and 5 below
LATER = NOW + timedelta(hours=6)  # when the repair is made: the same day, once Ollama works again


@pytest.fixture
def config(tmp_path):
    config = Config(data_dir=str(tmp_path / "data"))
    config.rss.feeds = [FEED]
    config.final_story_count = 5
    return config  # LeetCode exercises are on, as they are by default


@pytest.fixture
def model(monkeypatch):
    model = Tutor()
    model.selected = [3, 1, 2, 4, 5]  # laptop, Model X, Sparse attention, Dense attention, agent framework
    monkeypatch.setattr(llm, "chat_json", model.chat_json)
    monkeypatch.setattr(llm, "unload", model.unload)
    return model


@pytest.fixture
def degraded_run(config, fake_web, model, fake_articles):
    """Run 11, as on 2026-10-14: five stories, three summaries and the lesson failed, the exercise shown."""
    conn = db.connect(config.db_path)
    with conn:  # ten earlier runs, so that this one is run 11
        conn.executemany("INSERT INTO runs (run_date, created_at, digest_path) VALUES ('2026-10-01', '', '')", [()] * 10)
    conn.close()
    model.failing_titles = set(FAILING)
    model.lesson_error = llm.LLMError("Ollama did not answer within 120 s")
    _, model_ok = pipeline.run(config, now=NOW)
    assert not model_ok
    original = history.find_run(config, 11)
    model.failing_titles, model.lesson_error = set(), None
    model.summary_requests.clear()
    model.lesson_requests.clear()
    model.hint_requests.clear()
    return original


@pytest.fixture
def no_fetching(monkeypatch):
    """A repair fetches no source: only the failed stories' own pages, through articles."""

    def get(*args, **kwargs):
        raise AssertionError("a repair fetched a news source")

    monkeypatch.setattr(web, "get", get)


def document(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def rows(config, query):
    conn = sqlite3.connect(config.db_path)
    try:
        return conn.execute(query).fetchall()
    finally:
        conn.close()


def state(config):
    """Every table a repair must leave alone, and the source preferences."""
    tables = ["runs", "story_resets", "leetcode_assignments", "leetcode_showings", "leetcode_outcomes", "leetcode_progress",
              "leetcode_turns", "recalls"]  # fmt: skip
    return {table: rows(config, f"SELECT * FROM {table} ORDER BY rowid") for table in tables}


# --- the run 11 case


def test_repairing_run_11_keeps_the_five_stories_and_fills_in_what_failed(config, degraded_run, model, no_fetching):
    before = document(degraded_run["json"])
    original_bytes = Path(degraded_run["json"]).read_bytes(), Path(degraded_run["markdown"]).read_bytes()

    result = repair.repair(config, 11, "2026-10-07", now=LATER)

    assert result["outcome"] == "repaired" and result["status"] == "ok" and result["written"]
    assert result["revision"] == 1 and result["previous_revision"] == 0
    assert result["repaired"] == {"stories": [2, 4, 5], "lesson": True}
    assert result["remaining"] == {"stories": [], "lesson": False, "leetcode": False}
    after = document(result["json"])

    # The same five stories, in the same order, with the same identity.
    identity = ["id", "title", "source", "url"]
    assert [[s[k] for k in identity] for s in after["stories"]] == [[s[k] for k in identity] for s in before["stories"]]
    assert [s["title"] for s in after["stories"]] == [
        "Running LLMs on a laptop", "Model X released", "Sparse attention", "Dense attention", "An AI agent framework",
    ]  # fmt: skip
    # The two that succeeded are untouched; the three that failed now have summaries.
    assert after["stories"][0] == before["stories"][0] and after["stories"][2] == before["stories"][2]
    for number in (2, 4, 5):
        story = after["stories"][number - 1]
        assert story["what_happened"] == f"Summary of {story['title']}." and story["model_failed"] is False
        assert story["evidence"] == "article"
    assert sorted(model.summary_requests) == sorted(FAILING)  # only the failed ones were asked for
    assert model.lesson_requests == [SCHEDULE[0].title] and model.hint_requests == []
    assert model.unloads == 2  # the run's and the repair's

    # The lesson is the one the run should have given; everything else is as the run wrote it.
    assert after["lesson"]["topic_id"] == SCHEDULE[0].id and after["lesson"]["lesson"] == lesson_text(SCHEDULE[0].title)
    for key in ("schema_version", "run_id", "date", "generated_at", "model", "failed_sources", "sources", "leetcode"):
        assert after[key] == before[key], key
    assert after["leetcode"]["problem_id"] and after["leetcode"]["reference_solution"]
    assert after["status"] == "ok" and before["status"] == "degraded"
    assert after["repair"] == {
        "revision": 1, "repaired_at": LATER.isoformat(timespec="seconds"), "model": config.ollama.model,
        "original_status": "degraded", "previous_revision": 0,
        "repaired": {"stories": [2, 4, 5], "lesson": True},
        "remaining": {"stories": [], "lesson": False, "leetcode": False},
    }  # fmt: skip

    # The original archive is exactly as it was; the revision is a pair of its own.
    assert (Path(degraded_run["json"]).read_bytes(), Path(degraded_run["markdown"]).read_bytes()) == original_bytes
    assert Path(result["json"]).parent == config.repair_archive_dir / "2026-10-07"
    assert Path(result["json"]).name == Path(degraded_run["json"]).stem + "-r1.json"


def test_the_repaired_markdown_is_what_the_run_would_have_rendered(config, degraded_run, no_fetching):
    before = Path(degraded_run["markdown"]).read_text(encoding="utf-8")
    result = repair.repair(config, 11, now=LATER)
    after = Path(result["markdown"]).read_text(encoding="utf-8")

    assert render.describes(after, document(result["json"]))
    assert render.MODEL_FAILED_NOTE in before and render.MODEL_FAILED_NOTE not in after
    assert render.NO_LESSON_NOTE in before and render.NO_LESSON_NOTE not in after
    assert "**What happened:** Summary of Dense attention." in after
    assert f"**{SCHEDULE[0].title}**" in after
    leetcode_section = before[before.index("## LeetCode Micro-Lesson") :]
    assert after.endswith(leetcode_section)  # the exercise is byte for byte the run's
    assert after.split("### 2.")[0] == before.split("### 2.")[0]  # so is everything before the first repaired story


def test_repair_markdown_equals_a_full_rendering(make_candidate):
    """The patch is exactly the difference between a failed and a successful rendering, excerpt note included."""
    candidates = [make_candidate(title=f"Story {n}", kind="rss", source="Lab Blog") for n in range(1, 4)]
    failed = [Story(candidates[0], "One.", "Matters.", "article"), Story(candidates[1], model_failed=True),
              Story(candidates[2], model_failed=True)]  # fmt: skip
    fixed = {2: Story(candidates[1], "Two.", "Also matters.", "excerpt"), 3: Story(candidates[2], "Three.", "Yes.", "article")}
    day_ = NOW.date()
    lesson = repair.Lesson(SCHEDULE[0], "A lesson long enough to be plausible.", recall=None)

    patched = render.repair_markdown(render.render_digest(day_, failed, [], None), fixed, lesson)

    assert patched == render.render_digest(day_, [failed[0], fixed[2], fixed[3]], [], lesson)


def test_markdown_that_is_not_the_runs_rendering_is_refused_before_the_model_is_asked(config, degraded_run, model):
    path = Path(degraded_run["markdown"])
    path.chmod(0o644)
    text = path.read_text(encoding="utf-8").replace(render.MODEL_FAILED_NOTE, "_Edited by hand._", 1)
    path.write_text(text, encoding="utf-8")

    with pytest.raises(repair.RepairError) as raised:
        repair.repair(config, 11, now=LATER)

    assert raised.value.code == "markdown_mismatch"
    assert model.summary_requests == [] and model.lesson_requests == []
    assert history.repairs(config, degraded_run) == []


# --- what the database records


def test_the_database_records_what_the_run_would_have_and_nothing_else(config, degraded_run, no_fetching):
    untouched = state(config)
    shown_before = rows(config, "SELECT title FROM items WHERE shown_run_id = 11 ORDER BY title")
    assert shown_before == [("Running LLMs on a laptop",), ("Sparse attention",)]
    assert rows(config, "SELECT COUNT(*) FROM lessons") == [(0,)]

    repair.repair(config, 11, now=LATER)

    # The repaired stories count as shown by run 11, each with its summary, as if the model had not failed.
    assert rows(config, "SELECT title FROM items WHERE shown_run_id = 11 ORDER BY title") == [
        ("An AI agent framework",), ("Dense attention",), ("Model X released",), ("Running LLMs on a laptop",),
        ("Sparse attention",),
    ]  # fmt: skip
    assert rows(config, "SELECT COUNT(*) FROM summaries WHERE run_id = 11") == [(5,)]
    # The curriculum advanced by the one lesson the run should have given, and no more.
    assert rows(config, "SELECT run_id, topic_id FROM lessons") == [(11, SCHEDULE[0].id)]
    assert db.lesson_history(db.connect(config.db_path)) == [SCHEDULE[0].id]
    # No run was recorded, no exercise assigned or shown again, no story memory reset.
    assert state(config) | {"recalls": untouched["recalls"]} == untouched
    assert rows(config, "SELECT COUNT(*) FROM items") == [(6,)]  # nothing fetched, so nothing new seen


def test_the_next_run_neither_repeats_the_repaired_stories_nor_the_lesson(config, degraded_run, model):
    repair.repair(config, 11, now=LATER)

    digest, _ = pipeline.run(config, now=LATER)  # a rerun the same day

    assert "GPT wrappers considered harmful" in digest  # the only story never shown
    for title in FAILING:
        assert title not in digest
    assert read_latest(config)["lesson"]["topic_id"] == SCHEDULE[0].id  # the day's lesson, reused
    assert model.lesson_requests == [SCHEDULE[0].title]  # asked once, by the repair
    exercise = read_latest(config)["leetcode"]
    assert exercise["exercise_id"] == 1 and exercise["day"] == 1  # the same exercise, on the same day


def test_a_story_a_later_run_has_shown_since_keeps_that_showing(conn, make_candidate):
    candidate = make_candidate(title="Shown later")
    db.record_seen(conn, [candidate], NOW)
    first = db.record_run(conn, NOW.date(), Path("a.md"), [], NOW)  # the model failed on it here
    later = db.record_run(conn, NOW.date(), Path("b.md"), [candidate], NOW)  # and a later run showed it

    assert not db.record_repaired_showing(conn, first, Story(candidate, "What.", "Why.", "article"), "m", NOW)

    assert conn.execute("SELECT shown_run_id FROM items").fetchall() == [(later,)]
    assert conn.execute("SELECT COUNT(*) FROM repeat_showings").fetchone() == (0,)


def test_a_story_shown_before_a_reset_is_recorded_as_a_repeat_showing(conn, make_candidate):
    candidate = make_candidate(title="Shown again")
    db.record_seen(conn, [candidate], NOW)
    earlier = db.record_run(conn, NOW.date(), Path("a.md"), [candidate], NOW)
    conn.commit()
    db.reset_story_memory(conn, NOW)
    failed = db.record_run(conn, NOW.date(), Path("b.md"), [], NOW)

    assert db.record_repaired_showing(conn, failed, Story(candidate, "What.", "Why.", "article"), "m", NOW)

    assert conn.execute("SELECT shown_run_id FROM items").fetchall() == [(earlier,)]  # the first showing stays
    assert conn.execute("SELECT run_id, what_happened FROM repeat_showings").fetchall() == [(failed, "What.")]
    assert db.was_shown(conn, candidate)


# --- repeating, failing, partial repairs


def test_a_second_repair_finds_nothing_to_do_and_writes_nothing(config, degraded_run, model):
    first = repair.repair(config, 11, now=LATER)
    files = sorted(config.digest_dir.rglob("*"))
    model.summary_requests.clear()
    model.lesson_requests.clear()

    second = repair.repair(config, 11, now=LATER + timedelta(minutes=5))

    assert second["outcome"] == "nothing_to_repair" and not second["written"]
    assert second["revision"] == first["revision"] == 1 and second["status"] == "ok"
    assert second["json"] == first["json"]
    assert sorted(config.digest_dir.rglob("*")) == files
    assert model.summary_requests == [] and model.lesson_requests == []


def test_a_complete_digest_is_not_regenerated(config, fake_web, model, fake_articles):
    pipeline.run(config, now=NOW)
    model.summary_requests.clear()

    result = repair.repair(config, 1, now=LATER)

    assert result["outcome"] == "nothing_to_repair" and result["revision"] == 0 and result["status"] == "ok"
    assert result["attempted"] == {"stories": [], "lesson": False}
    assert model.summary_requests == [] and model.unloads == 1  # the run's own; the model was not even loaded
    assert not config.repair_archive_dir.exists()


def test_ollama_failing_again_changes_nothing_and_can_be_retried(config, degraded_run, model):
    model.error = llm.LLMError("cannot reach Ollama at http://localhost:11434")
    untouched = state(config), rows(config, "SELECT * FROM items ORDER BY id"), rows(config, "SELECT * FROM lessons")
    latest = config.latest_json_path.read_bytes()

    result = repair.repair(config, 11, now=LATER)

    assert result["outcome"] == "unchanged" and not result["written"] and result["status"] == "degraded"
    assert result["revision"] == 0 and result["remaining"] == {"stories": [2, 4, 5], "lesson": True, "leetcode": False}
    assert (state(config), rows(config, "SELECT * FROM items ORDER BY id"), rows(config, "SELECT * FROM lessons")) == untouched
    assert config.latest_json_path.read_bytes() == latest and not config.repair_archive_dir.exists()
    assert model.unloads == 2  # unloaded all the same

    model.error = None
    assert repair.repair(config, 11, now=LATER)["outcome"] == "repaired"


def test_a_partial_repair_keeps_what_worked_and_the_next_retries_only_the_rest(config, degraded_run, model, fake_articles):
    fake_articles["https://example.com/agents"] = OSError("page unavailable")  # story 5's page cannot be fetched

    first = repair.repair(config, 11, now=LATER)

    assert first["outcome"] == "partial" and first["status"] == "degraded" and first["revision"] == 1
    assert first["repaired"] == {"stories": [2, 4], "lesson": True}
    assert first["remaining"] == {"stories": [5], "lesson": False, "leetcode": False}
    revision_1 = Path(first["json"]).read_bytes()
    assert document(first["json"])["stories"][4]["model_failed"] is True  # still marked, to be tried again
    assert rows(config, "SELECT shown_run_id FROM items WHERE title = 'An AI agent framework'") == [(None,)]

    del fake_articles["https://example.com/agents"]
    model.summary_requests.clear()
    model.lesson_requests.clear()
    second = repair.repair(config, 11, now=LATER + timedelta(hours=1))

    assert model.summary_requests == ["An AI agent framework"] and model.lesson_requests == []
    assert second["outcome"] == "repaired" and second["revision"] == 2 and second["previous_revision"] == 1
    assert second["repaired"] == {"stories": [5], "lesson": False}
    final = document(second["json"])
    assert final["status"] == "ok" and final["repair"]["original_status"] == "degraded"
    assert final["stories"][:4] == document(first["json"])["stories"][:4]
    assert Path(first["json"]).read_bytes() == revision_1  # each revision is kept as it was written
    assert [entry["revision"] for entry in history.repairs(config, degraded_run)] == [1, 2]
    assert rows(config, "SELECT COUNT(*) FROM lessons") == [(1,)]


DESCRIBED_RSS = RSS_BODY.replace(
    b"<pubDate>", b"<description>" + b"Model X is a new open-weights model from the lab. " * 6 + b"</description><pubDate>"
)


def test_a_story_whose_page_cannot_be_read_is_summarised_from_its_feeds_description(config, degraded_run, fake_web,
                                                                                     fake_articles, monkeypatch):  # fmt: skip
    fake_articles["https://lab.example/model-x"] = OSError("403 Client Error: Forbidden")
    fake_web[FEED.url] = DESCRIBED_RSS
    fetched = []
    real_get = web.get
    monkeypatch.setattr(web, "get", lambda url, params=None: fetched.append(url) or real_get(url, params))

    result = repair.repair(config, 11, now=LATER)

    assert result["outcome"] == "repaired" and result["repaired"]["stories"] == [2, 4, 5]
    model_x = document(result["json"])["stories"][1]
    assert model_x["title"] == "Model X released" and model_x["evidence"] == "excerpt"
    assert fetched == [FEED.url]  # only that story's own source, once; no shortlist, no selection
    markdown = Path(result["markdown"]).read_text(encoding="utf-8")
    assert "(summarised from the feed excerpt; the full article could not be retrieved)" in markdown
    assert rows(config, "SELECT COUNT(*) FROM items") == [(6,)]  # nothing in the feed was recorded as seen


def test_a_story_its_source_no_longer_describes_stays_failed(config, degraded_run, fake_web, fake_articles):
    fake_articles["https://lab.example/model-x"] = OSError("403 Client Error: Forbidden")
    fake_web[FEED.url] = OSError("feed down")

    result = repair.repair(config, 11, now=LATER)

    assert result["outcome"] == "partial" and result["remaining"]["stories"] == [2]
    assert document(result["json"])["stories"][1]["model_failed"] is True


def test_a_repair_meeting_another_repair_writes_nothing(config, degraded_run, monkeypatch):
    real = history.latest_revision
    calls = []

    def moved_on(config, run):  # the second look, inside the transaction, sees a revision that appeared meanwhile
        calls.append(run)
        found = real(config, run)
        return found if len(calls) == 1 else found | {"revision": found["revision"] + 1}

    monkeypatch.setattr(history, "latest_revision", moved_on)

    with pytest.raises(repair.RepairError) as raised:
        repair.repair(config, 11, now=LATER)

    assert raised.value.code == "concurrent_repair"
    assert not config.repair_archive_dir.exists() or not list(config.repair_archive_dir.rglob("*.json"))
    assert rows(config, "SELECT COUNT(*) FROM lessons") == [(0,)]


# --- the lesson and the curriculum


def test_a_lesson_another_run_gave_that_day_is_used_and_not_generated_again(config, degraded_run, model):
    pipeline.run(config, now=LATER)  # a rerun the same day, whose lesson succeeded
    rerun_lesson = read_latest(config)["lesson"]
    model.lesson_requests.clear()

    result = repair.repair(config, 11, now=LATER + timedelta(hours=1))

    assert result["repaired"]["lesson"] is True and model.lesson_requests == []
    assert document(result["json"])["lesson"] == rerun_lesson
    assert rows(config, "SELECT COUNT(*) FROM lessons") == [(1,)]  # the rerun's; the curriculum moved once


def test_no_lesson_is_generated_once_a_later_day_has_moved_the_curriculum_on(config, degraded_run, model):
    pipeline.run(config, now=day(1))  # the next day's run gives the lesson the failed run should have
    model.lesson_requests.clear()

    result = repair.repair(config, 11, now=day(1))

    assert result["lesson_note"] == "curriculum_moved_on" and model.lesson_requests == []
    assert result["repaired"] == {"stories": [2, 4, 5], "lesson": False}
    assert result["status"] == "degraded" and result["remaining"]["lesson"] is True
    assert rows(config, "SELECT run_id FROM lessons") == [(12,)]


# --- the dated and latest files, history


def test_the_dated_and_latest_files_show_the_repair_while_they_hold_that_run(config, degraded_run):
    result = repair.repair(config, 11, now=LATER)

    assert result["current_files"] == ["dated", "latest"]
    assert config.latest_json_path.read_bytes() == Path(result["json"]).read_bytes()
    assert config.latest_markdown_path.read_bytes() == Path(result["markdown"]).read_bytes()
    assert (config.digest_dir / "2026-10-07.json").read_bytes() == Path(result["json"]).read_bytes()


def test_files_that_cannot_be_replaced_leave_the_revision_archived_and_say_so(config, degraded_run, monkeypatch, capsys):
    def broken(path, text):
        raise OSError("disk full")

    monkeypatch.setattr(repair.output, "write_atomic", broken)

    result = repair.repair(config, 11, now=LATER)

    assert result["written"] and result["current_files"] == [] and result["current_files_error"] == "disk full"
    assert Path(result["json"]).is_file() and rows(config, "SELECT COUNT(*) FROM lessons") == [(1,)]
    assert read_latest(config)["repair"] is None  # still the run's own digest


def test_a_later_runs_files_are_left_alone(config, degraded_run, model):
    pipeline.run(config, now=LATER)  # run 12 now holds the dated and latest files
    latest = config.latest_json_path.read_bytes()

    result = repair.repair(config, 11, now=LATER + timedelta(hours=1))

    assert result["current_files"] == [] and config.latest_json_path.read_bytes() == latest
    assert read_latest(config)["run_id"] == 12


def test_a_repaired_latest_json_is_recognised_as_archived(config, degraded_run, caplog):
    repair.repair(config, 11, now=LATER)

    results = history.backfill(config)
    history.preserve_latest(config)

    assert {result["outcome"] for result in results} == {"already_archived"}
    assert "was not archived" not in caplog.text


def test_history_lists_repairs_under_their_run_and_shows_each(config, degraded_run, capsys):
    result = repair.repair(config, 11, now=LATER)

    assert cli.main(["history", "--json", "--config", str(write_config(config))]) == 0
    listed = json.loads(capsys.readouterr().out)
    (run,) = [run for run in listed["runs"] if run["run_id"] == 11]
    assert run["status"] == "degraded"  # the run as it was
    assert [(r["revision"], r["status"], r["json"]) for r in run["repairs"]] == [(1, "ok", result["json"])]

    assert cli.main(["history", "show", "11", "--revision", "1", "--config", str(write_config(config))]) == 0
    assert capsys.readouterr().out == Path(result["json"]).read_text(encoding="utf-8")
    assert cli.main(["history", "show", "11", "--config", str(write_config(config))]) == 0
    assert json.loads(capsys.readouterr().out)["repair"] is None
    assert cli.main(["history", "show", "11", "--revision", "2", "--config", str(write_config(config))]) == 2

    assert cli.main(["history", "--config", str(write_config(config))]) == 0
    assert "repair 1" in capsys.readouterr().out


# --- the command


def write_config(config):
    path = Path(config.data_dir).parent / "dailygrad.toml"
    path.write_text(f'data_dir = "{config.data_dir}"\n', encoding="utf-8")
    return path


def test_cli_repair_reports_as_json_and_exits_by_the_final_status(config, degraded_run, capsys):
    toml = str(write_config(config))

    assert cli.main(["repair", "--run", "11", "--date", "2026-10-07", "--dry-run", "--json", "--config", toml]) == 1
    dry = json.loads(capsys.readouterr().out)
    assert dry["outcome"] == "dry_run" and dry["attempted"] == {"stories": [2, 4, 5], "lesson": True}
    assert not config.repair_archive_dir.exists()

    assert cli.main(["repair", "--run", "11", "--json", "--config", toml]) == 0
    done = json.loads(capsys.readouterr().out)
    assert done["ok"] is True and done["outcome"] == "repaired" and done["revision"] == 1

    assert cli.main(["repair", "--run", "11", "--config", toml]) == 0
    assert "nothing to repair" in capsys.readouterr().out


def test_cli_repair_refusals(config, degraded_run, capsys):
    toml = str(write_config(config))
    for argv, code in (
        (["--run", "99"], "not_found"),
        (["--run", "11", "--date", "2026-10-08"], "not_found"),
        (["--run", "11", "--date", "14/10/2026"], "bad_date"),
        (["--run", "0"], "bad_run_id"),
    ):
        assert cli.main(["repair", *argv, "--json", "--config", toml]) == 2, argv
        assert json.loads(capsys.readouterr().out)["error"]["code"] == code
    with pytest.raises(SystemExit):
        cli.main(["repair", "--config", toml])  # --run is required


def test_cli_repair_with_ollama_down_exits_1_and_says_so(config, degraded_run, model, capsys):
    model.error = llm.LLMError("cannot reach Ollama")

    assert cli.main(["repair", "--run", "11", "--config", str(write_config(config))]) == 1

    assert "the model failed again" in capsys.readouterr().out


def test_a_story_whose_id_does_not_match_its_url_is_refused(config, degraded_run):
    story = document(degraded_run["json"])["stories"][1] | {"id": "example.com/something-else"}

    with pytest.raises(repair.RepairError) as raised:
        repair._candidate(story, NOW)

    assert raised.value.code == "invalid_digest"


def test_a_paper_is_summarised_from_its_page_since_its_abstract_was_not_kept(monkeypatch):
    paper = {"id": "arxiv.org/abs/1", "title": "T", "source": "Hugging Face Daily Papers", "url": "https://arxiv.org/abs/1"}
    candidate = repair._candidate(paper, NOW)
    monkeypatch.setattr(stories.articles, "fetch_article_text", lambda url: "Text of the paper's page. " * 20)

    assert isinstance(candidate, Candidate) and candidate.kind == "huggingface" and candidate.summary == ""
    assert stories.gather_evidence(candidate)[1] == "article"
