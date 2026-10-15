"""SQLite history: news items seen and shown, their summaries, digest runs, lessons and recall questions,
and the LeetCode exercises assigned, the runs that showed each, how each ended, the exchanges about them
and what the user says of each problem.

A story is not shown twice. "Shown" is judged within the current story-memory epoch: a row
in story_resets starts a new epoch, after which stories shown earlier may be shown again.
Nothing is deleted or rewritten by a reset. An item's first showing stays where it always
was (items.shown_run_id and summaries); a later showing of the same item is a row in
repeat_showings.
"""

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import NamedTuple

from dailygrad.models import Candidate, Exercise, Lesson, Story

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    run_date TEXT NOT NULL,
    created_at TEXT NOT NULL,
    digest_path TEXT NOT NULL
);

-- One row per news item that reached a shortlist. shown_run_id stays NULL
-- until the item actually appears in a digest.
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY,
    url_key TEXT NOT NULL UNIQUE,
    title_key TEXT NOT NULL,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    shown_run_id INTEGER REFERENCES runs(id)
);

CREATE INDEX IF NOT EXISTS items_title_key ON items(title_key);

-- The summary written for a shown item. Shown items that could not be summarised have no row.
CREATE TABLE IF NOT EXISTS summaries (
    item_id INTEGER PRIMARY KEY REFERENCES items(id),
    run_id INTEGER NOT NULL REFERENCES runs(id),
    what_happened TEXT NOT NULL,
    why_it_matters TEXT NOT NULL,
    evidence TEXT NOT NULL,  -- 'article', 'abstract' or 'excerpt'
    model TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- A story-memory reset. Showings in runs up to and including after_run_id no longer stop a
-- story from being shown again; the newest row is the one in force.
CREATE TABLE IF NOT EXISTS story_resets (
    id INTEGER PRIMARY KEY,
    reset_at TEXT NOT NULL,
    after_run_id INTEGER NOT NULL  -- the newest run when the reset was made, 0 if there was none
);

-- An item shown again after a reset, with the summary written for that showing (NULL if it
-- was listed without one). The item's first showing is never moved here.
CREATE TABLE IF NOT EXISTS repeat_showings (
    item_id INTEGER NOT NULL REFERENCES items(id),
    run_id INTEGER NOT NULL REFERENCES runs(id),
    what_happened TEXT,
    why_it_matters TEXT,
    evidence TEXT,
    model TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (item_id, run_id)
);

-- One row per micro-lesson shown. Curriculum progress is derived from this table alone.
CREATE TABLE IF NOT EXISTS lessons (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    topic_id TEXT NOT NULL,  -- a curriculum topic id
    lesson TEXT NOT NULL,
    model TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- One row per recall question shown.
CREATE TABLE IF NOT EXISTS recalls (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    topic_id TEXT NOT NULL,
    question TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- One row per LeetCode exercise assigned. An exercise is not a day: the newest one stays the
-- current exercise, shown again in each digest (leetcode_showings), until the user completes or
-- skips it (leetcode_outcomes). The rotation and each track's progress are derived from this
-- table alone, so showing an exercise again advances neither. Being shown says nothing about
-- being solved.
CREATE TABLE IF NOT EXISTS leetcode_assignments (
    id INTEGER PRIMARY KEY,
    -- The first run that showed it. 0 for an exercise `dailygrad leetcode next` assigned between
    -- runs, until a run shows it.
    run_id INTEGER NOT NULL REFERENCES runs(id),
    problem_id TEXT NOT NULL,  -- a catalog problem id (the LeetCode slug)
    track TEXT NOT NULL,  -- the track whose turn it was
    review INTEGER NOT NULL,  -- 1 if the problem had been assigned before
    hint TEXT,  -- the hint written for it, once, and shown each day; NULL until one is, which is never while hints are off
    hint_source TEXT,  -- 'model' or 'catalog'
    model TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- One row per run whose digest showed an exercise: the day-by-day record of each exercise.
CREATE TABLE IF NOT EXISTS leetcode_showings (
    run_id INTEGER PRIMARY KEY REFERENCES runs(id),
    assignment_id INTEGER NOT NULL REFERENCES leetcode_assignments(id),
    created_at TEXT NOT NULL
);

-- How an exercise ended, by the user's own word: at most one row for each. The newest exercise
-- is the active one while it has no row here. An older exercise without one is from before
-- exercises were kept until completed: the next day's simply followed it.
CREATE TABLE IF NOT EXISTS leetcode_outcomes (
    assignment_id INTEGER PRIMARY KEY REFERENCES leetcode_assignments(id),
    outcome TEXT NOT NULL,  -- 'completed' or 'skipped'; neither is "solved in code" (leetcode_progress)
    closed_at TEXT NOT NULL
);

-- One row per interactive exchange about an exercise: a further hint, an answer with the
-- feedback on it, or a look at the reference approach.
CREATE TABLE IF NOT EXISTS leetcode_turns (
    id INTEGER PRIMARY KEY,
    assignment_id INTEGER NOT NULL REFERENCES leetcode_assignments(id),
    problem_id TEXT NOT NULL,
    kind TEXT NOT NULL,  -- 'hint', 'answer' or 'review'
    user_text TEXT,  -- the answer as sent; NULL for a hint or a review
    reply TEXT NOT NULL,  -- what was returned, as JSON
    model TEXT,  -- NULL when no model was used
    created_at TEXT NOT NULL
);

-- What the user says about a problem. `attempted_at` is also set by the first answer that
-- describes an approach; the other two are set only by `dailygrad leetcode mark`, never by a
-- showing or by feedback.
CREATE TABLE IF NOT EXISTS leetcode_progress (
    problem_id TEXT PRIMARY KEY,
    attempted_at TEXT,
    confidence TEXT,  -- 'needs-review' or 'comfortable'
    solved_at TEXT,  -- when the user said they had solved it in code
    updated_at TEXT NOT NULL
);

-- Why an exercise was chosen, by the practice mode in force (practice.py): at most one row each,
-- written with the exercise. An exercise from before practice modes has none.
CREATE TABLE IF NOT EXISTS leetcode_schedule (
    assignment_id INTEGER PRIMARY KEY REFERENCES leetcode_assignments(id),
    mode TEXT NOT NULL,  -- 'coverage', 'loop' or 'learning'
    sources TEXT NOT NULL,  -- the selected source IDs, as a JSON list
    encounter TEXT NOT NULL,  -- 'first' (never assigned before), 'repeat' or 'review' (a learning-mode review)
    cycle_id INTEGER REFERENCES leetcode_cycles(id),  -- loop mode: the cycle it belongs to
    review_number INTEGER,  -- a review: 1 for the first after the problem's first completion
    due_on TEXT,  -- a review: the day it became due, YYYY-MM-DD
    created_at TEXT NOT NULL
);

-- One row per loop-mode cycle: every problem of the pool once, in an order shuffled when the
-- cycle began and kept, so a restart neither reshuffles nor resets it. The open cycle is the
-- one without `ended`; a cycle's progress is its exercises in leetcode_schedule.
CREATE TABLE IF NOT EXISTS leetcode_cycles (
    id INTEGER PRIMARY KEY,
    number INTEGER NOT NULL,  -- 1 for the first cycle of a practice session, counting on across source changes
    sources TEXT NOT NULL,  -- the source IDs whose problems it holds, as a JSON list
    problems TEXT NOT NULL,  -- the problem IDs in the order they are assigned, as a JSON list
    started_at TEXT NOT NULL,
    ended TEXT,  -- 'completed'; 'sources_changed' if the selection changed before it was; 'reset' by a new session
    ended_at TEXT
);

-- A fresh coverage pass, asked for by the user. Exercises up to and including after_assignment_id
-- belong to earlier passes; the newest row is the pass in force, and with none every exercise is
-- in the first. Nothing else is changed by starting a pass.
CREATE TABLE IF NOT EXISTS leetcode_coverage_passes (
    id INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    after_assignment_id INTEGER NOT NULL
);

-- A reset of question progress, asked for by the user (`dailygrad leetcode practice restart-questions`):
-- the questions it covers are eligible again, in every mode, as if never practised. For each
-- question, its exercises up to and including after_assignment_id of the newest reset that
-- covers it belong to an earlier practice period, and no longer count; a question no reset
-- covers counts everything. A reset of `all` also begins a new practice session: loop cycles up
-- to and including after_cycle_id, and coverage passes, belong to earlier sessions. Nothing
-- else is changed: earlier exercises, outcomes, marks and exchanges stay, for the record and for
-- statistics.
CREATE TABLE IF NOT EXISTS leetcode_practice_resets (
    id INTEGER PRIMARY KEY,
    reset_at TEXT NOT NULL,
    after_assignment_id INTEGER NOT NULL,
    after_cycle_id INTEGER NOT NULL,
    scope TEXT NOT NULL DEFAULT 'all',  -- 'all', 'sources' (named ones) or 'selected' (those selected then)
    sources TEXT,  -- the source IDs it was given, as a JSON list; NULL for 'all'
    problems TEXT  -- the problem IDs it covers, fixed when it was made, as a JSON list; NULL for 'all'
);
"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    _upgrade_resets(conn)
    _backfill_showings(conn)
    return conn


RESET_SCOPE_COLUMNS = (("scope", "TEXT NOT NULL DEFAULT 'all'"), ("sources", "TEXT"), ("problems", "TEXT"))


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _upgrade_resets(conn: sqlite3.Connection) -> None:
    """Give leetcode_practice_resets from before scoped resets their scope columns: each of its rows reset everything."""
    missing = [(name, kind) for name, kind in RESET_SCOPE_COLUMNS if name not in _columns(conn, "leetcode_practice_resets")]
    if missing:
        with conn:
            for name, kind in missing:
                conn.execute(f"ALTER TABLE leetcode_practice_resets ADD COLUMN {name} {kind}")


def _backfill_showings(conn: sqlite3.Connection) -> None:
    """Give each exercise from before leetcode_showings existed the one showing it is known to have had.

    That is the run its row names. Rows are only added, and only once: afterwards every
    exercise a run has shown has a showing, and this finds nothing to do.
    """
    missing = (
        "FROM leetcode_assignments a WHERE a.run_id > 0"
        " AND NOT EXISTS (SELECT 1 FROM leetcode_showings s WHERE s.run_id = a.run_id)"
    )
    if conn.execute(f"SELECT 1 {missing} LIMIT 1").fetchone():
        with conn:
            conn.execute(
                "INSERT OR IGNORE INTO leetcode_showings (run_id, assignment_id, created_at)"
                f" SELECT a.run_id, a.id, a.created_at {missing}"
            )


def recorded_runs(path: Path) -> list[tuple[int, str, str]]:
    """Every run as (id, run date, created at), oldest first, read without creating or changing the database."""
    if not path.is_file():
        return []
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        return conn.execute("SELECT id, run_date, created_at FROM runs ORDER BY id").fetchall()
    except sqlite3.OperationalError:  # no runs table: a database that has never held a run
        return []
    finally:
        conn.close()


# Items shown in the current epoch, i.e. in a run after the newest reset. `:epoch` is that reset's run.
SHOWN_SINCE = "(shown_run_id > :epoch OR id IN (SELECT item_id FROM repeat_showings WHERE run_id > :epoch))"


def story_epoch(conn: sqlite3.Connection) -> int:
    """The run ID the newest story-memory reset was made after, or 0 if there has been no reset."""
    (epoch,) = conn.execute(
        "SELECT COALESCE((SELECT after_run_id FROM story_resets ORDER BY id DESC LIMIT 1), 0)"
    ).fetchone()
    return epoch


def was_shown(conn: sqlite3.Connection, candidate: Candidate) -> bool:
    """Whether this story, by URL or by title, has been shown since the last story-memory reset."""
    row = conn.execute(
        f"SELECT 1 FROM items WHERE (url_key = :url OR title_key = :title) AND {SHOWN_SINCE} LIMIT 1",
        {"url": candidate.url_key, "title": candidate.title_key, "epoch": story_epoch(conn)},
    ).fetchone()
    return row is not None


def story_memory(path: Path) -> dict:
    """What a story-memory reset would affect, read without creating or changing the database.

    `remembered` is the number of stories currently held back from being shown again.
    """
    empty = {"exists": False, "remembered": 0, "runs": 0, "last_run_id": 0, "resets": 0, "last_reset_at": None}
    if not path.is_file():
        return empty
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        tables = {name for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if not {"runs", "items"} <= tables:
            return empty | {"exists": True}
        runs, last_run_id = conn.execute("SELECT COUNT(*), COALESCE(MAX(id), 0) FROM runs").fetchone()
        resets, last_reset_at, epoch = 0, None, 0
        if "story_resets" in tables:  # a database from before resets existed has neither table
            (resets,) = conn.execute("SELECT COUNT(*) FROM story_resets").fetchone()
            if resets:
                last_reset_at, epoch = conn.execute(
                    "SELECT reset_at, after_run_id FROM story_resets ORDER BY id DESC LIMIT 1"
                ).fetchone()
        shown = SHOWN_SINCE if "repeat_showings" in tables else "shown_run_id > :epoch"
        (remembered,) = conn.execute(f"SELECT COUNT(*) FROM items WHERE {shown}", {"epoch": epoch}).fetchone()
    finally:
        conn.close()
    return {
        "exists": True, "remembered": remembered, "runs": runs, "last_run_id": last_run_id,
        "resets": resets, "last_reset_at": last_reset_at,
    }  # fmt: skip


def reset_story_memory(conn: sqlite3.Connection, now: datetime) -> int:
    """Start a new story-memory epoch: stories shown so far may be shown again. Returns how many that frees.

    Only a row in story_resets is added. With nothing to free, nothing is written.
    """
    with conn:
        conn.execute("BEGIN IMMEDIATE")  # a run recording at this moment finishes first, and is then included
        epoch = story_epoch(conn)
        (freed,) = conn.execute(f"SELECT COUNT(*) FROM items WHERE {SHOWN_SINCE}", {"epoch": epoch}).fetchone()
        if freed:
            conn.execute(
                "INSERT INTO story_resets (reset_at, after_run_id) SELECT ?, COALESCE(MAX(id), 0) FROM runs",
                (now.isoformat(),),
            )
    return freed


def record_seen(conn: sqlite3.Connection, candidates: list[Candidate], now: datetime) -> None:
    conn.executemany(
        "INSERT INTO items (url_key, title_key, source, title, url, first_seen_at)"
        " VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(url_key) DO NOTHING",
        [(c.url_key, c.title_key, c.source, c.title, c.url, now.isoformat()) for c in candidates],
    )


def record_run(
    conn: sqlite3.Connection, run_date: date, digest_path: Path, shown: list[Candidate], now: datetime
) -> int:
    """Record a digest run and mark the items it showed. Items must already be recorded as seen.

    An item shown for the first time gets this run as its shown_run_id. One that was shown
    before (possible only after a story-memory reset) keeps its original run and gets a row
    in repeat_showings for this one.
    """
    cursor = conn.execute(
        "INSERT INTO runs (run_date, created_at, digest_path) VALUES (?, ?, ?)",
        (run_date.isoformat(), now.isoformat(), str(digest_path)),
    )
    run_id = cursor.lastrowid
    conn.executemany(  # before the UPDATE below, so only items that already had a showing match
        "INSERT INTO repeat_showings (item_id, run_id, created_at)"
        " SELECT id, ?, ? FROM items WHERE url_key = ? AND shown_run_id IS NOT NULL",
        [(run_id, now.isoformat(), c.url_key) for c in shown],
    )
    conn.executemany(
        "UPDATE items SET shown_run_id = ? WHERE url_key = ? AND shown_run_id IS NULL",
        [(run_id, c.url_key) for c in shown],
    )
    return run_id


def record_summaries(conn: sqlite3.Connection, run_id: int, stories: list[Story], model: str, now: datetime) -> None:
    """Save the summaries of a run's stories. Call after record_run; items must already be recorded as seen.

    An item's first summary is never replaced. The summary of a repeat showing goes on its
    repeat_showings row.
    """
    summarised = [s for s in stories if s.what_happened]
    conn.executemany(
        "UPDATE repeat_showings SET what_happened = ?, why_it_matters = ?, evidence = ?, model = ?"
        " WHERE run_id = ? AND item_id = (SELECT id FROM items WHERE url_key = ?)",
        [(s.what_happened, s.why_it_matters, s.evidence, model, run_id, s.candidate.url_key) for s in summarised],
    )
    conn.executemany(
        "INSERT INTO summaries (item_id, run_id, what_happened, why_it_matters, evidence, model, created_at)"
        " SELECT id, ?, ?, ?, ?, ?, ? FROM items WHERE url_key = ? AND shown_run_id = ?"
        " ON CONFLICT(item_id) DO NOTHING",
        [
            (run_id, s.what_happened, s.why_it_matters, s.evidence, model, now.isoformat(), s.candidate.url_key, run_id)
            for s in summarised
        ],
    )


def record_repaired_showing(conn: sqlite3.Connection, run_id: int, story: Story, model: str, now: datetime) -> bool:
    """Record a story that a repair summarised for run `run_id` as that run would have. Returns False if it changed nothing.

    The run did not record it as shown, because the model failed on it. A repair records it now,
    as the run would have had the model not failed: as the item's first showing, with its summary,
    or, for an item shown before a story-memory reset, as a repeat showing. An item that a later
    run has shown since keeps that showing, and nothing is changed: the later run's record stands.
    """
    row = conn.execute("SELECT id, shown_run_id FROM items WHERE url_key = ?", (story.candidate.url_key,)).fetchone()
    if row is None:  # every shortlisted item is recorded as seen, so this is not a story of that run
        return False
    item_id, shown_run_id = row
    summary = (story.what_happened, story.why_it_matters, story.evidence, model, now.isoformat())
    if shown_run_id is None:
        conn.execute("UPDATE items SET shown_run_id = ? WHERE id = ?", (run_id, item_id))
        conn.execute(
            "INSERT INTO summaries (item_id, run_id, what_happened, why_it_matters, evidence, model, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(item_id) DO NOTHING",
            (item_id, run_id, *summary),
        )
        return True
    shown_later = conn.execute(
        "SELECT 1 FROM repeat_showings WHERE item_id = ? AND run_id > ? LIMIT 1", (item_id, run_id)
    ).fetchone()
    if shown_run_id >= run_id or shown_later:
        return False
    cursor = conn.execute(
        "INSERT INTO repeat_showings (item_id, run_id, what_happened, why_it_matters, evidence, model, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(item_id, run_id) DO NOTHING",
        (item_id, run_id, *summary),
    )
    return cursor.rowcount == 1


def lessons_after(conn: sqlite3.Connection, run_id: int) -> bool:
    """Whether a run after `run_id` has recorded a lesson, i.e. moved the curriculum on since."""
    return conn.execute("SELECT 1 FROM lessons WHERE run_id > ? LIMIT 1", (run_id,)).fetchone() is not None


def lesson_history(conn: sqlite3.Connection) -> list[str]:
    """Topic IDs of every lesson given, oldest first."""
    return [topic_id for (topic_id,) in conn.execute("SELECT topic_id FROM lessons ORDER BY id")]


def recall_history(conn: sqlite3.Connection) -> list[str]:
    """Topic IDs of every recall question asked, oldest first."""
    return [topic_id for (topic_id,) in conn.execute("SELECT topic_id FROM recalls ORDER BY id")]


def lesson_on(conn: sqlite3.Connection, day: date) -> tuple[str, str, str | None] | None:
    """The lesson given on `day`, as (topic id, lesson text, recall topic id or None), or None if there was none."""
    return conn.execute(
        "SELECT lessons.topic_id, lessons.lesson, recalls.topic_id FROM lessons"
        " JOIN runs ON runs.id = lessons.run_id"
        " LEFT JOIN recalls ON recalls.run_id = lessons.run_id"
        " WHERE runs.run_date = ? ORDER BY lessons.id DESC LIMIT 1",
        (day.isoformat(),),
    ).fetchone()


def record_lesson(conn: sqlite3.Connection, run_id: int, lesson: Lesson, model: str, now: datetime) -> None:
    """Save a lesson and its recall question, if any. This is what advances the curriculum."""
    conn.execute(
        "INSERT INTO lessons (run_id, topic_id, lesson, model, created_at) VALUES (?, ?, ?, ?, ?)",
        (run_id, lesson.topic.id, lesson.text, model, now.isoformat()),
    )
    if lesson.recall:
        conn.execute(
            "INSERT INTO recalls (run_id, topic_id, question, created_at) VALUES (?, ?, ?, ?)",
            (run_id, lesson.recall.id, lesson.recall.question, now.isoformat()),
        )


# --- LeetCode exercises

OUTCOMES = ("completed", "skipped")


class Assigned(NamedTuple):
    """One exercise as the database holds it."""

    id: int
    problem_id: str
    track: str
    review: int
    hint: str | None
    hint_source: str | None
    run_date: str | None  # the day a digest first showed it; None if none has yet
    created_at: str
    outcome: str | None  # 'completed' or 'skipped'; None while it is open
    closed_at: str | None


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone() is not None


def _exercises(conn: sqlite3.Connection) -> str:
    """The SELECT every exercise query starts with: the columns of Assigned, from leetcode_assignments as `a`.

    A read-only connection (see read_only) may be on a database from before exercises had
    outcomes. It is read as it is: every exercise in it is open.
    """
    columns = "a.id, a.problem_id, a.track, a.review, a.hint, a.hint_source, runs.run_date, a.created_at"
    source = "FROM leetcode_assignments a LEFT JOIN runs ON runs.id = a.run_id"
    if not _has_table(conn, "leetcode_outcomes"):
        return f"SELECT {columns}, NULL, NULL {source}"
    return f"SELECT {columns}, o.outcome, o.closed_at {source} LEFT JOIN leetcode_outcomes o ON o.assignment_id = a.id"


def _assigned(row: tuple | None) -> Assigned | None:
    return Assigned._make(row) if row else None


def leetcode_history(conn: sqlite3.Connection) -> list[str]:
    """Problem IDs of every exercise assigned, oldest first: one for each, however many days it was shown."""
    return [problem_id for (problem_id,) in conn.execute("SELECT problem_id FROM leetcode_assignments ORDER BY id")]


def leetcode_on(conn: sqlite3.Connection, day: date) -> Assigned | None:
    """The exercise a run showed on `day`, or None. It stays that day's exercise, whatever happened to it since."""
    return _assigned(
        conn.execute(
            f"{_exercises(conn)} JOIN leetcode_showings s ON s.assignment_id = a.id"
            " JOIN runs shown ON shown.id = s.run_id WHERE shown.run_date = ? ORDER BY s.run_id DESC LIMIT 1",
            (day.isoformat(),),
        ).fetchone()
    )


def latest_leetcode(conn: sqlite3.Connection, problem_id: str | None = None) -> Assigned | None:
    """The newest exercise assigned, or the newest of `problem_id`."""
    return _assigned(
        conn.execute(
            f"{_exercises(conn)} WHERE :problem IS NULL OR a.problem_id = :problem ORDER BY a.id DESC LIMIT 1",
            {"problem": problem_id},
        ).fetchone()
    )


def active_leetcode(conn: sqlite3.Connection) -> Assigned | None:
    """The exercise still waiting for the user to complete or skip it: the newest, unless it is closed."""
    newest = latest_leetcode(conn)
    return newest if newest and newest.outcome is None else None


def leetcode_by_id(conn: sqlite3.Connection, assignment_id: int) -> Assigned | None:
    return _assigned(conn.execute(f"{_exercises(conn)} WHERE a.id = ?", (assignment_id,)).fetchone())


def leetcode_before(conn: sqlite3.Connection, assignment_id: int) -> int | None:
    """The ID of the exercise assigned just before this one, or None if it was the first."""
    (previous,) = conn.execute("SELECT MAX(id) FROM leetcode_assignments WHERE id < ?", (assignment_id,)).fetchone()
    return previous


def leetcode_days(conn: sqlite3.Connection, assignment_id: int) -> list[str]:
    """The days on which a digest showed an exercise, oldest first."""
    if _has_table(conn, "leetcode_showings"):
        shown = "leetcode_showings s JOIN runs ON runs.id = s.run_id WHERE s.assignment_id = ?"
    else:  # read-only, on a database from before showings were kept: the one run its row names
        shown = "leetcode_assignments a JOIN runs ON runs.id = a.run_id WHERE a.id = ?"
    rows = conn.execute(f"SELECT DISTINCT runs.run_date FROM {shown} ORDER BY runs.run_date", (assignment_id,))
    return [run_date for (run_date,) in rows]


def leetcode_outcomes(conn: sqlite3.Connection) -> dict[str, int]:
    """How many exercises the user has completed, and how many skipped."""
    counts = dict.fromkeys(OUTCOMES, 0)
    if _has_table(conn, "leetcode_outcomes"):
        counts.update(conn.execute("SELECT outcome, COUNT(*) FROM leetcode_outcomes GROUP BY outcome").fetchall())
    return counts


def record_leetcode(conn: sqlite3.Connection, run_id: int, exercise: Exercise, model: str, now: datetime) -> int:
    """Save a newly assigned exercise. This is what advances the rotation and the track.

    `run_id` is the run showing it, or 0 when it is assigned between runs.
    """
    cursor = conn.execute(
        "INSERT INTO leetcode_assignments (run_id, problem_id, track, review, hint, hint_source, model, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            run_id, exercise.problem.id, exercise.track, int(exercise.review),
            exercise.hint or None, exercise.hint_source or None, model, now.isoformat(),
        ),
    )  # fmt: skip
    return cursor.lastrowid


def record_leetcode_showing(conn: sqlite3.Connection, run_id: int, assignment_id: int, now: datetime) -> None:
    """Record that a run's digest showed an exercise. This advances nothing: the same exercise may be shown for days."""
    conn.execute(
        "INSERT INTO leetcode_showings (run_id, assignment_id, created_at) VALUES (?, ?, ?)",
        (run_id, assignment_id, now.isoformat()),
    )
    conn.execute("UPDATE leetcode_assignments SET run_id = ? WHERE id = ? AND run_id = 0", (run_id, assignment_id))


def close_leetcode(conn: sqlite3.Connection, assignment_id: int, outcome: str, now: datetime) -> bool:
    """Record how an exercise ended. Returns False, changing nothing, if it had ended already."""
    if outcome not in OUTCOMES:
        raise ValueError(f"unknown outcome: {outcome}")
    cursor = conn.execute(
        "INSERT INTO leetcode_outcomes (assignment_id, outcome, closed_at) VALUES (?, ?, ?)"
        " ON CONFLICT(assignment_id) DO NOTHING",
        (assignment_id, outcome, now.isoformat()),
    )
    return cursor.rowcount == 1


def save_leetcode_hint(conn: sqlite3.Connection, assignment_id: int, hint: str, source: str) -> None:
    """Keep the hint written for an exercise that had none, so every later run shows the same one."""
    conn.execute(
        "UPDATE leetcode_assignments SET hint = ?, hint_source = ? WHERE id = ? AND hint IS NULL",
        (hint, source, assignment_id),
    )


def leetcode_turns(conn: sqlite3.Connection, assignment_id: int) -> list[tuple[str, str | None, str]]:
    """The exchanges about one exercise, oldest first, as (kind, the user's text, the reply as JSON)."""
    return conn.execute(
        "SELECT kind, user_text, reply FROM leetcode_turns WHERE assignment_id = ? ORDER BY id", (assignment_id,)
    ).fetchall()


def record_leetcode_turn(
    conn: sqlite3.Connection, assignment_id: int, problem_id: str, kind: str, user_text: str | None, reply: str,
    model: str | None, now: datetime,
) -> None:  # fmt: skip
    """Save one exchange about an exercise. It changes nothing else: see mark_leetcode for progress."""
    conn.execute(
        "INSERT INTO leetcode_turns (assignment_id, problem_id, kind, user_text, reply, model, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (assignment_id, problem_id, kind, user_text, reply, model, now.isoformat()),
    )


def leetcode_progress(conn: sqlite3.Connection) -> dict[str, tuple[str | None, str | None, str | None]]:
    """What the user has said of each problem, as {problem id: (attempted at, confidence, solved at)}."""
    rows = conn.execute("SELECT problem_id, attempted_at, confidence, solved_at FROM leetcode_progress")
    return {problem_id: (attempted_at, confidence, solved_at) for problem_id, attempted_at, confidence, solved_at in rows}


def mark_leetcode(
    conn: sqlite3.Connection, problem_id: str, now: datetime, attempted: bool = False,
    confidence: str | None = None, solved: bool = False, clear: bool = False,
) -> None:  # fmt: skip
    """Record what the user says of a problem. An earlier attempt or solve keeps its original time.

    `clear` withdraws the confidence and the solve. The showings and exchanges are history, and stay.
    """
    stamp = now.isoformat()
    conn.execute(
        "INSERT INTO leetcode_progress (problem_id, updated_at) VALUES (?, ?) ON CONFLICT(problem_id) DO NOTHING",
        (problem_id, stamp),
    )
    if clear:
        conn.execute("UPDATE leetcode_progress SET confidence = NULL, solved_at = NULL WHERE problem_id = ?", (problem_id,))
    if attempted or solved:  # solving it in code is also an attempt
        conn.execute(
            "UPDATE leetcode_progress SET attempted_at = COALESCE(attempted_at, ?) WHERE problem_id = ?",
            (stamp, problem_id),
        )
    if confidence:
        conn.execute("UPDATE leetcode_progress SET confidence = ? WHERE problem_id = ?", (confidence, problem_id))
    if solved:
        conn.execute(
            "UPDATE leetcode_progress SET solved_at = COALESCE(solved_at, ?) WHERE problem_id = ?", (stamp, problem_id)
        )
    conn.execute("UPDATE leetcode_progress SET updated_at = ? WHERE problem_id = ?", (stamp, problem_id))


# --- practice modes (practice.py decides; this only stores and reads)


class Scheduled(NamedTuple):
    """One exercise as the practice modes see it: its problem, how it ended and why it was chosen."""

    id: int
    problem_id: str
    outcome: str | None
    closed_at: str | None
    mode: str | None  # None for an exercise from before practice modes
    sources: tuple[str, ...] | None  # the sources selected when it was chosen
    encounter: str | None
    cycle_id: int | None
    review_number: int | None
    due_on: str | None


class Cycle(NamedTuple):
    id: int
    number: int
    sources: tuple[str, ...]
    problems: tuple[str, ...]
    started_at: str
    ended: str | None
    ended_at: str | None


def scheduled_history(conn: sqlite3.Connection) -> list[Scheduled]:
    """Every exercise, oldest first, with its outcome and its schedule row if it has them.

    A read-only connection may be on a database from before outcomes or schedules were kept:
    it is read as it is, with those parts empty.
    """
    if not _has_table(conn, "leetcode_assignments"):
        return []
    outcome = "o.outcome, o.closed_at" if _has_table(conn, "leetcode_outcomes") else "NULL, NULL"
    joins = " LEFT JOIN leetcode_outcomes o ON o.assignment_id = a.id" if _has_table(conn, "leetcode_outcomes") else ""
    schedule = "s.mode, s.sources, s.encounter, s.cycle_id, s.review_number, s.due_on"
    if _has_table(conn, "leetcode_schedule"):
        joins += " LEFT JOIN leetcode_schedule s ON s.assignment_id = a.id"
    else:
        schedule = "NULL, NULL, NULL, NULL, NULL, NULL"
    rows = conn.execute(f"SELECT a.id, a.problem_id, {outcome}, {schedule} FROM leetcode_assignments a{joins} ORDER BY a.id")
    return [Scheduled._make((*row[:5], tuple(json.loads(row[5])) if row[5] else None, *row[6:])) for row in rows]


def record_schedule(
    conn: sqlite3.Connection, assignment_id: int, mode: str, sources: tuple[str, ...], encounter: str,
    cycle_id: int | None, review_number: int | None, due_on: str | None, now: datetime,
) -> None:  # fmt: skip
    conn.execute(
        "INSERT INTO leetcode_schedule (assignment_id, mode, sources, encounter, cycle_id, review_number, due_on, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (assignment_id, mode, json.dumps(list(sources)), encounter, cycle_id, review_number, due_on, now.isoformat()),
    )


def _cycle(row: tuple) -> Cycle:
    return Cycle(row[0], row[1], tuple(json.loads(row[2])), tuple(json.loads(row[3])), *row[4:])


def cycles(conn: sqlite3.Connection) -> list[Cycle]:
    """Every loop-mode cycle, oldest first."""
    if not _has_table(conn, "leetcode_cycles"):
        return []
    rows = conn.execute("SELECT id, number, sources, problems, started_at, ended, ended_at FROM leetcode_cycles ORDER BY id")
    return [_cycle(row) for row in rows]


def start_cycle(conn: sqlite3.Connection, number: int, sources: tuple[str, ...], problems: list[str], now: datetime) -> Cycle:
    cursor = conn.execute(
        "INSERT INTO leetcode_cycles (number, sources, problems, started_at) VALUES (?, ?, ?, ?)",
        (number, json.dumps(list(sources)), json.dumps(problems), now.isoformat()),
    )
    return Cycle(cursor.lastrowid, number, tuple(sources), tuple(problems), now.isoformat(), None, None)


def end_cycle(conn: sqlite3.Connection, cycle_id: int, ended: str, now: datetime) -> None:
    conn.execute(
        "UPDATE leetcode_cycles SET ended = ?, ended_at = ? WHERE id = ? AND ended IS NULL", (ended, now.isoformat(), cycle_id)
    )


def coverage_passes(conn: sqlite3.Connection) -> list[tuple[str, int]]:
    """Every fresh coverage pass started, oldest first, as (started at, after assignment ID)."""
    if not _has_table(conn, "leetcode_coverage_passes"):
        return []
    return conn.execute("SELECT started_at, after_assignment_id FROM leetcode_coverage_passes ORDER BY id").fetchall()


def start_coverage_pass(conn: sqlite3.Connection, after_assignment_id: int, now: datetime) -> None:
    conn.execute(
        "INSERT INTO leetcode_coverage_passes (started_at, after_assignment_id) VALUES (?, ?)",
        (now.isoformat(), after_assignment_id),
    )


class Reset(NamedTuple):
    """A reset of question progress: the questions it covers start a new practice period after it."""

    id: int
    reset_at: str
    after_assignment_id: int
    after_cycle_id: int
    scope: str  # 'all', 'sources' or 'selected'
    sources: tuple[str, ...] | None  # None for 'all'
    problems: frozenset[str] | None  # the questions it covers; None for every one


def practice_resets(conn: sqlite3.Connection) -> list[Reset]:
    """Every reset of question progress, oldest first."""
    if not _has_table(conn, "leetcode_practice_resets"):
        return []
    scoped = "scope" in _columns(conn, "leetcode_practice_resets")  # read-only, from before scoped resets: all 'all'
    columns = "scope, sources, problems" if scoped else "'all', NULL, NULL"
    rows = conn.execute(
        f"SELECT id, reset_at, after_assignment_id, after_cycle_id, {columns} FROM leetcode_practice_resets ORDER BY id"
    )
    return [
        Reset(*row[:5], tuple(json.loads(row[5])) if row[5] else None, frozenset(json.loads(row[6])) if row[6] else None)
        for row in rows
    ]


def record_reset(
    conn: sqlite3.Connection, after_assignment_id: int, scope: str, sources: tuple[str, ...] | None,
    problems: list[str] | None, now: datetime,
) -> None:  # fmt: skip
    """Add a reset of question progress. `problems` None covers every question."""
    (after_cycle_id,) = conn.execute("SELECT COALESCE(MAX(id), 0) FROM leetcode_cycles").fetchone()
    conn.execute(
        "INSERT INTO leetcode_practice_resets (reset_at, after_assignment_id, after_cycle_id, scope, sources, problems)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (
            now.isoformat(), after_assignment_id, after_cycle_id, scope, json.dumps(list(sources)) if sources else None,
            json.dumps(problems) if problems is not None else None,
        ),
    )  # fmt: skip


def read_only(path: Path) -> sqlite3.Connection | None:
    """A connection that cannot change the database, or None if there is no database. Nothing is created.

    A database from before a table existed does not gain it this way: a query on it raises
    sqlite3.OperationalError, which the caller treats as "no rows".
    """
    if not path.is_file():
        return None
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
