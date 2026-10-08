"""The digest's output files: each run's archive, the dated Markdown and JSON, latest.md and latest.json.

Together with stdout and the exit code, these files are DailyGrad's public interface.
The JSON layout is documented in docs/output.md; change SCHEMA_VERSION if it changes
in a way that could break a consumer.
"""

import json
import os
from datetime import date, datetime
from pathlib import Path

from dailygrad import history
from dailygrad.config import Config
from dailygrad.curriculum import TRACKS
from dailygrad.models import Lesson, Story

SCHEMA_VERSION = 1


def digest_document(
    run_id: int,
    day: date,
    generated_at: datetime,
    model: str,
    stories: list[Story],
    failed_sources: list[str],
    lesson: Lesson | None,
    sources: list[dict],
) -> dict:
    """The digest as plain data, for the JSON files. Every key is always present; a missing value is null."""
    degraded = lesson is None or any(story.model_failed for story in stories)
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,  # the id of this run's row in the database
        "date": day.isoformat(),
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "status": "degraded" if degraded else "ok",
        "model": model,
        "stories": [_story(story) for story in stories],
        "failed_sources": list(failed_sources),
        "sources": sources,  # every available source, and whether this run fetched it
        "lesson": _lesson(lesson),
        "recall": _recall(lesson),
    }


def _story(story: Story) -> dict:
    candidate = story.candidate
    return {
        "id": candidate.url_key,  # the canonical URL: the same story keeps this ID from run to run
        "title": candidate.title,
        "source": candidate.source,
        "url": candidate.url,
        "what_happened": story.what_happened or None,
        "why_it_matters": story.why_it_matters or None,
        "evidence": story.evidence or None,
        "model_failed": story.model_failed,
    }


def _lesson(lesson: Lesson | None) -> dict | None:
    if lesson is None:
        return None
    topic = lesson.topic
    return {
        "topic_id": topic.id,
        "title": topic.title,
        "track": topic.track,
        "track_name": TRACKS[topic.track],
        "series": topic.series,
        "lesson": lesson.text,
    }


def _recall(lesson: Lesson | None) -> dict | None:
    if lesson is None or lesson.recall is None:
        return None
    return {"topic_id": lesson.recall.id, "question": lesson.recall.question}


def dated_markdown_path(config: Config, day: date) -> Path:
    return config.digest_dir / f"{day.isoformat()}.md"


def write_outputs(config: Config, day: date, markdown: str, document: dict) -> None:
    """Archive the run, then write the dated Markdown and JSON, then latest.md and latest.json, all the same.

    The archive comes first, so latest.json never names a run that has no archive. The dated
    and latest files are replaced; the archive is created once (see history.py) and stays.
    """
    json_text = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
    history.preserve_latest(config)  # the digest about to be replaced, if it predates the archives
    archived = history.archive_run(config, markdown, json_text)
    try:
        dated_path = dated_markdown_path(config, day)
        write_atomic(dated_path, markdown)
        write_atomic(dated_path.with_suffix(".json"), json_text)
        write_atomic(config.latest_markdown_path, markdown)
        write_atomic(config.latest_json_path, json_text)
    except BaseException:
        history.discard(archived)  # the run is rolled back, so no archive may name it
        raise


def write_atomic(path: Path, text: str) -> None:
    """Replace `path` with `text` in one step, so a reader or a crash never sees half a file.

    The text goes to a temporary file in the same directory, which is then renamed over the target.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        with open(temporary, "w", encoding="utf-8") as file:
            file.write(text)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
