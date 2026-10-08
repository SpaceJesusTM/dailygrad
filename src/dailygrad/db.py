"""SQLite history: news items seen and shown, their summaries, digest runs, lessons and recall questions."""

import sqlite3
from datetime import date, datetime
from pathlib import Path

from dailygrad.models import Candidate, Lesson, Story

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
"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn


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


def was_shown(conn: sqlite3.Connection, candidate: Candidate) -> bool:
    row = conn.execute(
        "SELECT 1 FROM items WHERE shown_run_id IS NOT NULL AND (url_key = ? OR title_key = ?) LIMIT 1",
        (candidate.url_key, candidate.title_key),
    ).fetchone()
    return row is not None


def record_seen(conn: sqlite3.Connection, candidates: list[Candidate], now: datetime) -> None:
    conn.executemany(
        "INSERT INTO items (url_key, title_key, source, title, url, first_seen_at)"
        " VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(url_key) DO NOTHING",
        [(c.url_key, c.title_key, c.source, c.title, c.url, now.isoformat()) for c in candidates],
    )


def record_run(
    conn: sqlite3.Connection, run_date: date, digest_path: Path, shown: list[Candidate], now: datetime
) -> int:
    """Record a digest run and mark the items it showed. Items must already be recorded as seen."""
    cursor = conn.execute(
        "INSERT INTO runs (run_date, created_at, digest_path) VALUES (?, ?, ?)",
        (run_date.isoformat(), now.isoformat(), str(digest_path)),
    )
    run_id = cursor.lastrowid
    conn.executemany(
        "UPDATE items SET shown_run_id = ? WHERE url_key = ? AND shown_run_id IS NULL",
        [(run_id, c.url_key) for c in shown],
    )
    return run_id


def record_summaries(conn: sqlite3.Connection, run_id: int, stories: list[Story], model: str, now: datetime) -> None:
    """Save the summaries of a run's stories. Items must already be recorded as seen."""
    conn.executemany(
        "INSERT INTO summaries (item_id, run_id, what_happened, why_it_matters, evidence, model, created_at)"
        " SELECT id, ?, ?, ?, ?, ?, ? FROM items WHERE url_key = ?"
        " ON CONFLICT(item_id) DO NOTHING",
        [
            (run_id, s.what_happened, s.why_it_matters, s.evidence, model, now.isoformat(), s.candidate.url_key)
            for s in stories
            if s.what_happened
        ],
    )


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
