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
from dailygrad.leetcode_catalog import CATEGORIES, PROMPTS
from dailygrad.models import Exercise, Lesson, Problem, Story

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
    exercise: Exercise | None = None,
    leetcode_failed: bool = False,
) -> dict:
    """The digest as plain data, for the JSON files. Every key is always present; a missing value is null.

    `exercise` is None when LeetCode exercises are switched off, and also when one was due and
    could not be prepared: `leetcode_failed` tells the two apart, and makes the run degraded.
    """
    degraded = lesson is None or leetcode_failed or any(story.model_failed for story in stories)
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
        "leetcode": leetcode_document(exercise),
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


def reference_solution(problem: Problem) -> dict | None:
    """The catalog's reference answer to a problem, for a program that tutors on it. None if the catalog has none.

    Every part is the catalog's own and was validated when the file was loaded: nothing here is
    written by the model, and nothing is filled in. A part the catalog does not have is null,
    and `complete` is then false. The topic alone is not an answer, so without any of the
    approach, the complexities and the edge cases there is no reference at all.
    """
    parts = {
        "approach": problem.approach.strip() or None,
        "time": problem.time.strip() or None,
        "space": problem.space.strip() or None,
        "edge_cases": [case for case in problem.edge_cases if case.strip()] or None,
    }
    if all(part is None for part in parts.values()):
        return None
    return {
        "source": "catalog",
        "complete": all(part is not None for part in parts.values()),
        "topic": CATEGORIES.get(problem.category),  # the pattern the problem is filed under
        **parts,
    }


def leetcode_document(exercise: Exercise | None, with_reference: bool = True) -> dict | None:
    """The exercise as a digest's JSON holds it.

    Every key but the last is what the digest shows. `reference_solution` is the answer: the
    catalog's approach, complexities and edge cases, for a program that gives feedback on the
    exercise. It is never in the Markdown, and a consumer that displays or summarises a digest
    must leave it out. The further hints and the spoiler words stay in the catalog.

    `with_reference=False` leaves that key out altogether, for output a person reads directly.
    """
    if exercise is None:
        return None
    problem = exercise.problem
    document = {
        "problem_id": problem.id,  # LeetCode's slug: permanent
        "number": problem.number,
        "title": problem.title,
        "url": problem.url,
        "difficulty": problem.difficulty,
        "premium": problem.premium,
        "track": exercise.track,  # the track whose turn it was
        "review": exercise.review,
        "sources": [
            {"id": source.id, "name": source.name, "kind": source.kind, "publisher": source.publisher}
            for source in exercise.sources
        ],
        # Companies a third party lists the problem under: not LeetCode's own company tags.
        "company_tags": [source.name for source in exercise.sources if source.kind == "company"],
        "statement": problem.statement,
        "example": {"input": problem.example_input, "output": problem.example_output},
        "constraints": list(problem.constraints),
        "prompts": list(PROMPTS),
        "hints_enabled": exercise.hints_on,
        "hint": exercise.shown_hint or None,
        "hint_source": (exercise.hint_source or None) if exercise.shown_hint else None,
        # The exercise is kept until the user completes or skips it, so a digest may show it again.
        "exercise_id": exercise.assignment_id,  # names this assignment of the problem: what to complete or skip
        "assigned_on": exercise.assigned_on,  # the day a digest first showed it
        "day": exercise.day,  # how many days it has been shown, this one included
        "is_carryover": exercise.day > 1,  # shown on an earlier day too: not a newly assigned exercise
        "awaiting_completion": exercise.outcome is None,  # false once completed or skipped
    }
    if with_reference:
        document["reference_solution"] = reference_solution(problem)  # the answer: never to be displayed unasked
    return document


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
