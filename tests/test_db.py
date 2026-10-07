import sqlite3

from conftest import NOW
from dailygrad import db
from dailygrad.models import Story


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
