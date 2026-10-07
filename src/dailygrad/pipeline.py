"""The run: fetch -> filter -> render -> save -> record history."""

import logging
from datetime import datetime, timezone
from functools import partial

from dailygrad import db
from dailygrad.config import Config
from dailygrad.filtering import build_shortlist
from dailygrad.models import Candidate
from dailygrad.render import render_digest
from dailygrad.sources import hackernews, huggingface, rss

log = logging.getLogger(__name__)


def run(config: Config, now: datetime | None = None) -> str:
    """Produce today's digest, save it and record it in the database. Returns the Markdown."""
    now = now or datetime.now(timezone.utc)
    today = now.astimezone().date()  # the digest is dated in local time

    candidates, failed_sources = fetch_all(config)

    conn = db.connect(config.db_path)
    try:
        shortlist = build_shortlist(candidates, config, conn, now)
        digest = render_digest(today, shortlist, failed_sources)

        config.digest_dir.mkdir(parents=True, exist_ok=True)
        digest_path = config.digest_dir / f"{today.isoformat()}.md"
        digest_path.write_text(digest, encoding="utf-8")

        with conn:  # one transaction
            db.record_seen(conn, shortlist, now)
            # Until the model picks 3-5 stories (Pass 2), the digest shows the whole shortlist.
            db.record_run(conn, today, digest_path, shown=shortlist, now=now)
    finally:
        conn.close()

    log.info("%d candidates fetched, %d in digest, saved to %s", len(candidates), len(shortlist), digest_path)
    return digest


def fetch_all(config: Config) -> tuple[list[Candidate], list[str]]:
    """Fetch every enabled source. Returns the candidates and the names of sources that failed.

    The order matters: deduplication keeps the first copy of a story, so the official
    feed or the paper entry is preferred over a Hacker News link to the same thing.
    """
    fetchers = [(feed.name, partial(rss.fetch, feed)) for feed in config.rss.feeds]
    if config.huggingface.enabled:
        fetchers.append(("Hugging Face Daily Papers", huggingface.fetch))
    if config.hackernews.enabled:
        fetchers.append(("Hacker News", hackernews.fetch))

    candidates, failed_sources = [], []
    for name, fetch in fetchers:
        try:
            candidates += fetch()
        except Exception as exc:  # one broken source must not abort the others
            log.warning("source %s failed: %s", name, exc)
            failed_sources.append(name)
    return candidates, failed_sources
