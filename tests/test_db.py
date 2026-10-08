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


# --- story-memory resets


def show(conn, candidates, minutes=0, summaries=None):
    """Record a run that showed `candidates`, summarised as `summaries` says. Returns the run ID."""
    when = NOW + timedelta(minutes=minutes)
    stories = [Story(c, *(summaries or {}).get(c.title, ())) for c in candidates]
    with conn:
        db.record_seen(conn, candidates, when)
        run_id = db.record_run(conn, when.date(), "digest.md", candidates, when)
        db.record_summaries(conn, run_id, stories, "test-model", when)
    return run_id


def rows(conn, sql):
    return conn.execute(sql).fetchall()


def test_reset_makes_shown_stories_eligible_and_new_showings_are_remembered_again(conn, make_candidate):
    old, other = make_candidate("Old story"), make_candidate("Other story")
    show(conn, [old, other])
    assert db.was_shown(conn, old) and db.was_shown(conn, other)

    assert db.reset_story_memory(conn, NOW) == 2
    assert not db.was_shown(conn, old) and not db.was_shown(conn, other)

    show(conn, [old], minutes=10)
    assert db.was_shown(conn, old)  # shown again, so excluded again
    assert not db.was_shown(conn, other)  # still free until it is shown


def test_reset_keeps_every_earlier_record(conn, make_candidate):
    story = make_candidate("Old story")
    first = show(conn, [story], summaries={"Old story": ("First summary.", "First reason.", "article")})
    with conn:
        db.record_lesson(conn, first, Lesson(make_topic("nn-backprop"), "A lesson."), "test-model", NOW)
    before = {table: rows(conn, f"SELECT * FROM {table}") for table in ("runs", "items", "summaries", "lessons", "recalls")}

    db.reset_story_memory(conn, NOW)

    assert {table: rows(conn, f"SELECT * FROM {table}") for table in before} == before
    assert rows(conn, "SELECT after_run_id FROM story_resets") == [(first,)]
    assert db.lesson_history(conn) == ["nn-backprop"]  # the curriculum is where it was


def test_a_story_shown_again_keeps_its_first_showing_and_gains_a_second_with_its_own_summary(conn, make_candidate):
    story = make_candidate("Old story")
    first = show(conn, [story], summaries={"Old story": ("First summary.", "First reason.", "article")})
    db.reset_story_memory(conn, NOW)

    second = show(conn, [story], minutes=10, summaries={"Old story": ("Second summary.", "Second reason.", "excerpt")})

    assert rows(conn, "SELECT shown_run_id FROM items") == [(first,)]  # the original association is untouched
    assert rows(conn, "SELECT run_id, what_happened, evidence FROM summaries") == [(first, "First summary.", "article")]
    assert rows(conn, "SELECT run_id, what_happened, why_it_matters, evidence, model FROM repeat_showings") == [
        (second, "Second summary.", "Second reason.", "excerpt", "test-model")
    ]


def test_a_story_can_be_shown_once_in_every_epoch(conn, make_candidate):
    story = make_candidate("Old story")
    runs = [show(conn, [story])]
    for number in (1, 2):
        assert db.reset_story_memory(conn, NOW) == 1
        runs.append(show(conn, [story], minutes=number, summaries={"Old story": (f"Summary {number}.", "Why.", "article")}))
        assert db.was_shown(conn, story)

    assert rows(conn, "SELECT run_id, what_happened FROM repeat_showings ORDER BY run_id") == [
        (runs[1], "Summary 1."), (runs[2], "Summary 2."),
    ]  # fmt: skip
    assert rows(conn, "SELECT after_run_id FROM story_resets ORDER BY id") == [(runs[0],), (runs[1],)]


def test_a_repeat_showing_without_a_summary_is_still_remembered(conn, make_candidate):
    story = make_candidate("Headline only")
    show(conn, [story])
    db.reset_story_memory(conn, NOW)

    run_id = show(conn, [story], minutes=10)  # no usable text, so listed without a summary

    assert rows(conn, "SELECT run_id, what_happened, model FROM repeat_showings") == [(run_id, None, None)]
    assert db.was_shown(conn, story)


def test_a_story_the_model_failed_on_after_a_reset_stays_eligible(conn, make_candidate):
    story = make_candidate("Old story")
    show(conn, [story])
    db.reset_story_memory(conn, NOW)

    when = NOW + timedelta(minutes=10)
    with conn:  # what the pipeline does for a failed summary: seen, but not among the shown
        db.record_seen(conn, [story], when)
        run_id = db.record_run(conn, when.date(), "digest.md", [], when)
        db.record_summaries(conn, run_id, [Story(story, model_failed=True)], "test-model", when)

    assert not db.was_shown(conn, story) and rows(conn, "SELECT * FROM repeat_showings") == []


def test_after_a_reset_a_repost_with_the_same_title_is_matched_only_against_new_showings(conn, make_candidate):
    show(conn, [make_candidate("Model X released", url="https://lab.example/model-x")])
    repost = make_candidate("Model X released", url="https://mirror.example/model-x")
    assert db.was_shown(conn, repost)

    db.reset_story_memory(conn, NOW)
    assert not db.was_shown(conn, repost)

    show(conn, [repost], minutes=10)
    assert db.was_shown(conn, make_candidate("Model X released", url="https://third.example/model-x"))
    assert rows(conn, "SELECT * FROM repeat_showings") == []  # a different item's first showing, not a repeat


def test_reset_with_nothing_remembered_writes_nothing(conn, make_candidate):
    assert db.reset_story_memory(conn, NOW) == 0

    show(conn, [make_candidate("Old story")])
    assert db.reset_story_memory(conn, NOW) == 1
    assert db.reset_story_memory(conn, NOW) == 0  # a second reset in a row has nothing to free

    assert len(rows(conn, "SELECT * FROM story_resets")) == 1


def test_a_database_from_before_resets_gains_the_tables_and_keeps_its_memory(tmp_path, make_candidate):
    """An existing database has neither new table. Connecting adds them, empty: no reset happens by itself."""
    path = tmp_path / "old.db"
    old_schema = db.SCHEMA.split("-- A story-memory reset.")[0] + "-- One row per micro-lesson shown." + db.SCHEMA.split("-- One row per micro-lesson shown.")[1]
    assert "story_resets" not in old_schema and "repeat_showings" not in old_schema
    old = sqlite3.connect(path)
    old.executescript(old_schema)
    old.execute("INSERT INTO runs VALUES (1, '2026-10-06', '2026-10-06T07:00:00+00:00', 'digest.md')")
    story = make_candidate("Old story")
    old.execute(
        "INSERT INTO items VALUES (1, ?, ?, 'Hacker News', 'Old story', ?, '2026-10-06T07:00:00+00:00', 1)",
        (story.url_key, story.title_key, story.url),
    )
    old.execute("INSERT INTO summaries VALUES (1, 1, 'Old summary.', 'Old reason.', 'article', 'old-model', '2026-10-06')")
    old.commit()
    old.close()
    assert db.story_memory(path) == {
        "exists": True, "remembered": 1, "runs": 1, "last_run_id": 1, "resets": 0, "last_reset_at": None,
    }  # fmt: skip

    conn = db.connect(path)
    assert db.was_shown(conn, story) and db.story_epoch(conn) == 0  # upgrading resets nothing
    assert rows(conn, "SELECT * FROM story_resets") == [] and rows(conn, "SELECT * FROM repeat_showings") == []

    db.reset_story_memory(conn, NOW)
    second = show(conn, [story], minutes=10, summaries={"Old story": ("New summary.", "New reason.", "article")})

    assert rows(conn, "SELECT run_id, what_happened, model FROM summaries") == [(1, "Old summary.", "old-model")]
    assert rows(conn, "SELECT run_id, what_happened FROM repeat_showings") == [(second, "New summary.")]
    conn.close()


def test_story_memory_reads_without_creating_or_changing_anything(tmp_path, make_candidate):
    assert db.story_memory(tmp_path / "missing.db")["exists"] is False
    assert not (tmp_path / "missing.db").exists()

    path = tmp_path / "test.db"
    conn = db.connect(path)
    show(conn, [make_candidate("One"), make_candidate("Two")])
    conn.close()
    before = path.read_bytes()

    assert db.story_memory(path)["remembered"] == 2
    assert path.read_bytes() == before
