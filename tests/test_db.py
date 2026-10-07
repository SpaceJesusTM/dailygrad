import sqlite3
from datetime import timedelta

from conftest import NOW
from dailygrad import db
from dailygrad.models import Lesson, Story, Topic


def test_seen_items_are_not_shown_until_a_run_records_them(conn, make_candidate):
    item = make_candidate()
    with conn:
        db.record_seen(conn, [item], NOW)
    assert not db.was_shown(conn, item)

    with conn:
        run_id = db.record_run(conn, NOW.date(), "2026-10-07.md", shown=[item], now=NOW)
    assert db.was_shown(conn, item)

    assert conn.execute("SELECT id, run_date, digest_path FROM runs").fetchall() == [
        (run_id, "2026-10-07", "2026-10-07.md")
    ]


def test_was_shown_matches_on_url_or_title(conn, make_candidate):
    item = make_candidate("Model X released", url="https://lab.example/model-x")
    with conn:
        db.record_seen(conn, [item], NOW)
        db.record_run(conn, NOW.date(), "digest.md", shown=[item], now=NOW)

    assert db.was_shown(conn, make_candidate("Different title", url="http://www.lab.example/model-x/"))
    assert db.was_shown(conn, make_candidate("model x: released", url="https://elsewhere.example/x"))
    assert not db.was_shown(conn, make_candidate("Unrelated", url="https://elsewhere.example/y"))


def test_recording_the_same_item_twice_keeps_one_row_and_the_first_run(conn, make_candidate):
    item = make_candidate()
    with conn:
        db.record_seen(conn, [item], NOW)
        first_run = db.record_run(conn, NOW.date(), "a.md", shown=[item], now=NOW)
        db.record_seen(conn, [item], NOW)
        db.record_run(conn, NOW.date(), "b.md", shown=[item], now=NOW)

    assert conn.execute("SELECT shown_run_id FROM items").fetchall() == [(first_run,)]


def test_history_survives_reconnecting(tmp_path, make_candidate):
    path = tmp_path / "nested" / "history.db"
    item = make_candidate()

    first = db.connect(path)
    with first:
        db.record_seen(first, [item], NOW)
        db.record_run(first, NOW.date(), "digest.md", shown=[item], now=NOW)
    first.close()

    second = db.connect(path)
    assert db.was_shown(second, item)
    second.close()


def test_summaries_are_saved_for_summarised_stories_only(conn, make_candidate):
    summarised = Story(make_candidate("Model X"), "X was released.", "It is small.", "article")
    headline_only = Story(make_candidate("Model Y"))
    candidates = [summarised.candidate, headline_only.candidate]
    with conn:
        db.record_seen(conn, candidates, NOW)
        run_id = db.record_run(conn, NOW.date(), "digest.md", shown=candidates, now=NOW)
        db.record_summaries(conn, run_id, [summarised, headline_only], "test-model", NOW)

    rows = conn.execute(
        "SELECT items.title, run_id, what_happened, why_it_matters, evidence, model"
        " FROM summaries JOIN items ON items.id = summaries.item_id"
    ).fetchall()
    assert rows == [("Model X", run_id, "X was released.", "It is small.", "article", "test-model")]


def test_phase_1_database_gains_the_summaries_table(tmp_path, make_candidate):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript(db.SCHEMA.split("-- The summary written")[0])  # the Phase 1 schema: runs and items only
    old.execute("INSERT INTO runs (run_date, created_at, digest_path) VALUES ('2026-10-06', 'then', 'old.md')")
    old.execute(
        "INSERT INTO items (url_key, title_key, source, title, url, first_seen_at, shown_run_id)"
        " VALUES ('example.com/old', 'old', 'Hacker News', 'Old', 'https://example.com/old', 'then', 1)"
    )
    old.commit()
    old.close()

    conn = db.connect(path)

    assert db.was_shown(conn, make_candidate("Old", url="https://example.com/old"))
    assert conn.execute("SELECT COUNT(*) FROM summaries").fetchone() == (0,)
    conn.close()


def make_topic(topic_id, question="Why?"):
    return Topic(topic_id, "foundations", "Series", 1, f"Title of {topic_id}", ("a", "b", "c"), question)


def test_lessons_and_recalls_are_recorded_in_order(conn):
    first, second = make_topic("nn-first", "What is first?"), make_topic("nn-second")
    assert db.lesson_history(conn) == [] and db.recall_history(conn) == []

    with conn:
        run_1 = db.record_run(conn, NOW.date(), "a.md", shown=[], now=NOW)
        db.record_lesson(conn, run_1, Lesson(first, "The first lesson."), "test-model", NOW)
        run_2 = db.record_run(conn, NOW.date(), "b.md", shown=[], now=NOW)
        db.record_lesson(conn, run_2, Lesson(second, "The second lesson.", recall=first), "test-model", NOW)

    assert db.lesson_history(conn) == ["nn-first", "nn-second"]
    assert db.recall_history(conn) == ["nn-first"]
    assert conn.execute("SELECT run_id, topic_id, lesson, model FROM lessons ORDER BY id").fetchall() == [
        (run_1, "nn-first", "The first lesson.", "test-model"),
        (run_2, "nn-second", "The second lesson.", "test-model"),
    ]
    assert conn.execute("SELECT run_id, topic_id, question FROM recalls").fetchall() == [
        (run_2, "nn-first", "What is first?")
    ]


def test_lesson_on_finds_the_lesson_given_on_a_date(conn):
    today, tomorrow = NOW.date(), (NOW + timedelta(days=1)).date()
    first, second = make_topic("nn-first"), make_topic("nn-second")
    assert db.lesson_on(conn, today) is None

    with conn:
        run_1 = db.record_run(conn, today, "a.md", shown=[], now=NOW)
        db.record_lesson(conn, run_1, Lesson(first, "The first lesson."), "test-model", NOW)
        db.record_run(conn, today, "a.md", shown=[], now=NOW)  # a rerun that recorded no lesson
        run_3 = db.record_run(conn, tomorrow, "b.md", shown=[], now=NOW)
        db.record_lesson(conn, run_3, Lesson(second, "The second lesson.", recall=first), "test-model", NOW)

    assert db.lesson_on(conn, today) == ("nn-first", "The first lesson.", None)
    assert db.lesson_on(conn, tomorrow) == ("nn-second", "The second lesson.", "nn-first")
    assert db.lesson_on(conn, (NOW + timedelta(days=2)).date()) is None


def test_lesson_history_survives_reconnecting(tmp_path):
    path = tmp_path / "history.db"
    first = db.connect(path)
    with first:
        run_id = db.record_run(first, NOW.date(), "a.md", shown=[], now=NOW)
        db.record_lesson(first, run_id, Lesson(make_topic("nn-first"), "A lesson.", recall=make_topic("nn-older")), "m", NOW)
    first.close()

    second = db.connect(path)
    assert db.lesson_history(second) == ["nn-first"]
    assert db.recall_history(second) == ["nn-older"]
    second.close()


def test_phase_2_database_gains_the_lesson_tables(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript(db.SCHEMA.split("-- One row per micro-lesson")[0])  # the Phase 2 schema
    old.execute("INSERT INTO runs (run_date, created_at, digest_path) VALUES ('2026-10-07', 'then', 'old.md')")
    old.commit()
    old.close()

    conn = db.connect(path)

    assert conn.execute("SELECT COUNT(*) FROM runs").fetchone() == (1,)  # existing history is kept
    assert db.lesson_history(conn) == [] and db.recall_history(conn) == []
    conn.close()
