"""The run: fetch -> filter -> select and summarise -> lesson -> render -> write outputs -> record history."""

import logging
from datetime import datetime, timezone
from functools import partial

from dailygrad import db, llm
from dailygrad.config import Config
from dailygrad.curriculum import load_curriculum
from dailygrad.filtering import build_shortlist
from dailygrad.lessons import build_lesson, restore_lesson
from dailygrad.models import Candidate
from dailygrad.output import dated_markdown_path, digest_document, write_outputs
from dailygrad.render import render_digest
from dailygrad.sources import hackernews, huggingface, rss
from dailygrad.stories import build_stories

log = logging.getLogger(__name__)


def run(config: Config, now: datetime | None = None) -> tuple[str, bool]:
    """Produce today's digest, write its output files and record it in the database.

    Returns the Markdown, and False if a model request failed. In that case the digest is
    still written (with status "degraded" in latest.json), but the stories the model failed
    on are not recorded as shown, and a failed lesson does not advance the curriculum.

    The curriculum advances once per calendar day: a rerun on the same day shows that day's
    lesson again instead of generating the next one.
    """
    now = now or datetime.now(timezone.utc)
    today = now.astimezone().date()  # the digest is dated in local time

    topics = load_curriculum()  # before any network or model work, so a broken file fails fast
    candidates, failed_sources = fetch_all(config)

    conn = db.connect(config.db_path)
    try:
        shortlist = build_shortlist(candidates, config, conn, now)

        lesson = restore_lesson(topics, db.lesson_on(conn, today))
        lesson_is_new = lesson is None  # no lesson yet today, or today's earlier attempt failed
        if lesson:
            log.info("reusing today's lesson: %s", lesson.topic.id)

        # News and lesson share one model load. The lesson is generated even on a day without news.
        try:
            stories = build_stories(shortlist, config.ollama, config.final_story_count) if shortlist else []
            if lesson_is_new:
                lesson = build_lesson(topics, db.lesson_history(conn), db.recall_history(conn), config.ollama)
        finally:
            llm.unload(config.ollama)  # free the model's memory even if generation raised

        digest = render_digest(today, stories, failed_sources, lesson)
        digest_path = dated_markdown_path(config, today)

        # One transaction. The files are written last, because they carry the run's id: if
        # writing fails the run is rolled back, so no file ever names a run that was not recorded.
        with conn:
            db.record_seen(conn, shortlist, now)
            # Only stories in the digest count as shown, and not those the model failed on:
            # they and the rest of the shortlist can come back in a later run.
            shown = [story.candidate for story in stories if not story.model_failed]
            run_id = db.record_run(conn, today, digest_path, shown, now)
            db.record_summaries(conn, run_id, stories, config.ollama.model, now)
            if lesson and lesson_is_new:  # recording a lesson is what advances the curriculum
                db.record_lesson(conn, run_id, lesson, config.ollama.model, now)
            document = digest_document(run_id, today, now, config.ollama.model, stories, failed_sources, lesson)
            write_outputs(config, today, digest, document)
    finally:
        conn.close()

    log.info(
        "%d candidates fetched, %d shortlisted, %d in digest, saved to %s",
        len(candidates), len(shortlist), len(stories), digest_path,
    )  # fmt: skip
    failures = sum(story.model_failed for story in stories)
    if failures:
        log.error("the model failed on %d of %d stories; they were not recorded as shown", failures, len(stories))
    return digest, document["status"] == "ok"


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
