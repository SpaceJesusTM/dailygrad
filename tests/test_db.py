from conftest import NOW
from dailygrad import db


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
