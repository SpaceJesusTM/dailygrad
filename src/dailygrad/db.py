"""SQLite history: which news items have been seen and shown, and when digests ran."""

import sqlite3
from datetime import date, datetime
from pathlib import Path

from dailygrad.models import Candidate

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
"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn


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
