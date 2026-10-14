"""Repair a degraded digest: ask the model again for what it failed on, and keep everything else.

A run whose model requests failed still writes its digest, with the failed stories listed
without a summary and no lesson. A repair takes that digest, never a new one: the same
stories in the same order, the summaries that succeeded as they are, the LeetCode exercise
and the sources untouched. It retries only the stories marked `model_failed` and, if there
was none, the lesson. Nothing is selected again, and nothing is fetched but the failed
stories' own pages and, for a story whose page gives no text (a site that refuses the
download, as the run's summary may have come from the feed's description, which the archive
does not keep), that story's own source, once, to find the same story's description again.
Nothing else found there is used or recorded.

The run's archive is never changed. The repaired digest is a new revision of the same run
(the same run_id, date and generated_at), archived beside it under repairs/ with a `repair`
object that says which revision it is and what it repaired. A later repair starts from the
newest revision, so what was repaired once is never asked for again, and a digest with
nothing left to repair is left alone. The dated and latest files are replaced only while
they still hold that run. The layout is documented in docs/output.md.

The database is changed as the run would have changed it, had the model not failed: a
repaired story is recorded as shown by that run (unless a later run has shown it since), and
a repaired lesson is recorded for it, which advances the curriculum by the one lesson the run
should have given. A lesson is not generated if a later run has given one since: the topic
would then come out of order. Story memory, source preferences and the LeetCode exercise and
its progress are not touched.
"""

import copy
import json
import logging
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path

from dailygrad import db, history, llm, output, render, stories
from dailygrad.config import Config
from dailygrad.curriculum import load_curriculum
from dailygrad.lessons import build_lesson, restore_lesson
from dailygrad.models import Candidate, Lesson, Story, Topic, canonical_url
from dailygrad.sources import available_sources

log = logging.getLogger(__name__)

# The source names DailyGrad gives these kinds of story; any other source is an RSS feed.
KINDS = {"Hacker News": "hackernews", "Hugging Face Daily Papers": "huggingface"}


class RepairError(history.HistoryError):
    """A repair that is refused. `code` is stable; the message is for a person."""


def repair(config: Config, run_id: int, day: str | None = None, now: datetime | None = None, dry_run: bool = False) -> dict:
    """Repair archived run `run_id` (of `day`, if given). Returns the result as documented in docs/output.md.

    Raises RepairError (a HistoryError) if the run cannot be found or its digest cannot be
    repaired, and lets database and file errors through. With `dry_run`, only says what a
    repair would retry: no model, no writes.
    """
    now = now or datetime.now(timezone.utc)
    run = history.find_run(config, run_id, day)
    source = history.latest_revision(config, run)
    document, markdown = _read(source)
    stories_missing = [number for number, story in enumerate(document["stories"], start=1) if story.get("model_failed")]
    lesson_missing = document.get("lesson") is None
    result = {
        "ok": True, "outcome": None, "run_id": run["run_id"], "date": run["date"], "generated_at": run["generated_at"],
        "previous_revision": source["revision"], "revision": source["revision"], "written": False,
        "status": document.get("status"),
        "attempted": {"stories": stories_missing, "lesson": lesson_missing},
        "repaired": {"stories": [], "lesson": False},
        "remaining": _remaining(document),
        "lesson_note": None, "current_files": [], "json": source["json"], "markdown": source["markdown"],
    }  # fmt: skip
    if not stories_missing and not lesson_missing:
        result["attempted"] = {"stories": [], "lesson": False}
        return result | {"outcome": "nothing_to_repair"}
    _check_markdown(markdown, document, stories_missing, lesson_missing)  # before any model time is spent
    if dry_run:
        return result | {"outcome": "dry_run"}

    llm.begin_run(config.run_budget_seconds)
    topics = load_curriculum()
    conn = db.connect(config.db_path)
    try:
        lesson, lesson_is_new = None, False
        if lesson_missing:
            lesson = restore_lesson(topics, db.lesson_on(conn, date.fromisoformat(run["date"])))
            if lesson:
                log.info("using the lesson another run gave on %s: %s", run["date"], lesson.topic.id)
            elif db.lessons_after(conn, run["run_id"]):
                result["lesson_note"] = "curriculum_moved_on"
                log.warning("not generating the lesson: a later run has moved the curriculum on since run %d", run_id)
            else:
                lesson_is_new = True

        repaired: dict[int, Story] = {}
        descriptions = _Descriptions(config)
        try:
            for number in stories_missing:
                story = _summarize(_candidate(document["stories"][number - 1], now), config, descriptions)
                if story.what_happened:
                    repaired[number] = story
                else:  # no usable text is a failure here too: the story stays marked, to be tried again
                    log.error("story %d (%s) is still not summarised", number, story.candidate.url)
            if lesson_is_new:
                lesson = build_lesson(topics, db.lesson_history(conn), db.recall_history(conn), config.ollama)
        finally:
            llm.unload(config.ollama)  # free the model's memory even if generation raised
        log.info(llm.usage())

        if not repaired and lesson is None:
            return result | {"outcome": "unchanged"}
        revision = source["revision"] + 1
        new_document = _repaired_document(document, repaired, lesson, revision, source, config, now)
        new_markdown = render.repair_markdown(markdown, repaired, lesson)
        json_text = json.dumps(new_document, indent=2, ensure_ascii=False) + "\n"

        # One transaction, as in a run: the archive is written last, and removed again if anything fails.
        created = []
        try:
            with conn:
                conn.execute("BEGIN IMMEDIATE")  # a run or another repair recording at this moment finishes first
                if history.latest_revision(config, run)["revision"] != source["revision"]:
                    message = f"run {run_id} was repaired by something else meanwhile; nothing was written"
                    raise RepairError("concurrent_repair", message)
                for story in repaired.values():
                    db.record_repaired_showing(conn, run["run_id"], story, config.ollama.model, now)
                if lesson and lesson_is_new:  # recording a lesson is what advances the curriculum
                    db.record_lesson(conn, run["run_id"], lesson, config.ollama.model, now)
                created = history.archive_run(config, new_markdown, json_text)
                # Still holding the write lock, so a run cannot replace these files between the check and the write.
                try:
                    current_files = output.replace_current(config, new_document, new_markdown)
                except OSError as exc:  # the revision is archived and recorded; only the convenience copies are behind
                    log.error("revision %d is archived, but the dated and latest files could not be updated: %s", revision, exc)
                    current_files = exc
        except BaseException:
            history.discard(created)
            raise
    except render.RepairMismatch as exc:
        raise RepairError("markdown_mismatch", f"run {run_id}'s Markdown is not DailyGrad's rendering of it: {exc}") from None
    finally:
        conn.close()

    json_path, markdown_path = history.archive_paths(config, new_document)
    log.info("archived revision %d of run %d: %s", revision, run_id, ", ".join(str(path) for path in created) or "already there")
    result |= {
        "outcome": "repaired" if new_document["status"] == "ok" else "partial",
        "revision": revision, "written": True, "status": new_document["status"],
        "repaired": {"stories": sorted(repaired), "lesson": lesson is not None},
        "remaining": _remaining(new_document),
        "json": str(json_path.resolve()), "markdown": str(markdown_path.resolve()),
    }  # fmt: skip
    if isinstance(current_files, OSError):
        result["current_files_error"] = str(current_files)
    else:
        result["current_files"] = current_files
    return result


def _read(source: dict) -> tuple[dict, str]:
    if not source["markdown"]:
        raise RepairError("no_markdown", f"run {source['run_id']} was archived without its Markdown, so it cannot be repaired")
    document = json.loads(Path(source["json"]).read_text(encoding="utf-8"))
    markdown = Path(source["markdown"]).read_text(encoding="utf-8")
    if not render.describes(markdown, document):
        raise RepairError("markdown_mismatch", f"run {source['run_id']}'s Markdown and JSON are not the same digest")
    return document, markdown


def _check_markdown(markdown: str, document: dict, numbers: list[int], lesson_missing: bool) -> None:
    """Raise RepairError unless the Markdown can take every repair that may be made: a trial with stand-ins."""
    stand_in = Story(_candidate(document["stories"][0], datetime.now(timezone.utc)), "-", "-") if numbers else None
    lesson = Lesson(Topic("-", "-", "-", 1, "-", (), "-"), "-") if lesson_missing else None
    try:
        render.repair_markdown(markdown, dict.fromkeys(numbers, stand_in), lesson)
    except render.RepairMismatch as exc:
        raise RepairError("markdown_mismatch", f"run {document['run_id']}'s Markdown is not DailyGrad's rendering of it: {exc}") from None


def _candidate(story: dict, now: datetime) -> Candidate:
    """The story as the summariser needs it. Its feed description was not kept, so only its page is used."""
    candidate = Candidate(
        kind=KINDS.get(story.get("source"), "rss"), source=story.get("source"), title=story.get("title"),
        url=story.get("url"), published=now,
    )  # fmt: skip
    if not all(isinstance(value, str) and value for value in (candidate.source, candidate.title, candidate.url)):
        raise RepairError("invalid_digest", "a story to repair has no title, source or URL")
    if canonical_url(candidate.url) != story.get("id"):
        raise RepairError("invalid_digest", f"a story's id does not match its URL: {candidate.url}")
    return candidate


def _summarize(candidate: Candidate, config: Config, descriptions: "_Descriptions") -> Story:
    """Summarise one story as a run would. Without usable page text, from its source's own description of it."""
    story = stories.summarize(candidate, config.ollama)
    if story.what_happened or story.model_failed:
        return story
    described = descriptions.find(candidate)
    return stories.summarize(described, config.ollama) if described else story


class _Descriptions:
    """A failed story's description as its source gives it: what a run summarises when the page cannot be read."""

    def __init__(self, config: Config):
        self.sources = {source.name: source for source in available_sources(config)}
        self.fetched: dict[str, list[Candidate]] = {}

    def find(self, candidate: Candidate) -> Candidate | None:
        """The story with its source's description, or None. Each source is fetched at most once per repair."""
        source = self.sources.get(candidate.source)
        if source is None:
            return None
        if source.name not in self.fetched:
            try:
                self.fetched[source.name] = source.fetch()
            except Exception as exc:  # as in a run, a broken source costs only what needed it
                log.warning("source %s failed: %s", source.name, exc)
                self.fetched[source.name] = []
        for found in self.fetched[source.name]:
            if found.url_key == candidate.url_key and len(found.summary) >= stories.MIN_EVIDENCE_CHARS:
                log.info("using %s's own description of %s", source.name, candidate.url)
                return replace(candidate, kind=found.kind, summary=found.summary)
        log.warning("%s no longer describes %s", source.name, candidate.url)
        return None


def _remaining(document: dict) -> dict:
    """What is still missing from a digest: failed stories by number, the lesson, the LeetCode exercise."""
    failed = [number for number, story in enumerate(document["stories"], start=1) if story.get("model_failed")]
    lesson = document.get("lesson") is None
    # A digest with neither failed stories nor a missing lesson is degraded only by its exercise.
    leetcode = document.get("status") == "degraded" and document.get("leetcode") is None and not failed and not lesson
    if document.get("repair"):
        leetcode = document["repair"]["remaining"]["leetcode"]  # carried, as the reason is gone by then
    return {"stories": failed, "lesson": lesson, "leetcode": leetcode}


def _repaired_document(
    document: dict, repaired: dict[int, Story], lesson: Lesson | None, revision: int, source: dict, config: Config,
    now: datetime,
) -> dict:  # fmt: skip
    """The next revision: `document` with the repaired parts filled in, its status and its provenance."""
    remaining_before = _remaining(document)
    new = copy.deepcopy(document)
    for number, story in repaired.items():
        new["stories"][number - 1] |= {
            "what_happened": story.what_happened, "why_it_matters": story.why_it_matters,
            "evidence": story.evidence, "model_failed": False,
        }  # fmt: skip
    if lesson is not None:
        new["lesson"] = output._lesson(lesson)
        new["recall"] = output._recall(lesson)
    remaining = _remaining(new) | {"leetcode": remaining_before["leetcode"]}
    new["status"] = "degraded" if remaining["stories"] or remaining["lesson"] or remaining["leetcode"] else "ok"
    previous = document.get("repair") or {}
    new["repair"] = {
        "revision": revision,
        "repaired_at": now.isoformat(timespec="seconds"),
        "model": config.ollama.model,
        "original_status": previous.get("original_status", document["status"]),
        "previous_revision": source["revision"],
        "repaired": {"stories": sorted(repaired), "lesson": lesson is not None},
        "remaining": remaining,
    }
    return new
