"""The LeetCode exercise: one catalog problem at a time, presented for conceptual practice.

An exercise is not a day. Once assigned it is the current exercise, and each day's digest shows
it again, until the user says they have completed it or asks to move on. Only then is the next
one chosen, so the rotation of tracks follows the user's pace and not the calendar.

The problem, its example and its constraints are printed from the catalog as written, so the
model cannot change the question, and it never chooses one. The model's single job here is to
word the hint, and what it writes is checked before it is shown: a hint that names the
approach is discarded for the catalog's own.

Whether a digest shows a hint is the user's choice, kept in <data_dir>/leetcode_preferences.json
beside the database, where Git never touches it and a code update leaves it alone.
"""

import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path

from dailygrad import db, llm
from dailygrad.config import Config
from dailygrad.leetcode_catalog import Catalog, gives_away, load_catalog, next_problem, track_for_day
from dailygrad.models import Exercise, Problem
from dailygrad.output import write_atomic

log = logging.getLogger(__name__)

PREFERENCES_VERSION = 1
HINT_TEMPERATURE = 0.0  # a hint restates an approved one, so take the model's most likely wording
MIN_HINT_CHARS = 20
MAX_HINT_CHARS = 240  # one sentence fits easily; more means the model started explaining
# Which problem a review day prefers among those shown equally often: lower comes first.
REVIEW_RANKS = {"needs-review": 0, None: 1, "comfortable": 2}
SOLVED_RANK = 3

HINT_SYSTEM = """\
You word the hint for a daily coding-interview exercise. The reader is practising how to choose \
a data structure and an algorithm, and has to work out the approach alone.

You will get the problem and an approved hint. Rewrite the approved hint as one gentle sentence \
of at most 30 words that gives the reader something to think about.

Rules:
- Say only what the approved hint says. Do not add an idea, a step or a detail of your own.
- Do not name a data structure, an algorithm or a technique unless the approved hint names it.
- Do not state a time or space complexity, and do not describe the solution or its steps.
- Do not restate the problem.
- One plain sentence: no lists, code, Markdown or quotation marks.

Reply with JSON of the form {"hint": "..."}."""

HINT_SCHEMA = {
    "type": "object",
    "properties": {"hint": {"type": "string"}},
    "required": ["hint"],
}


def daily_exercise(conn, day: date, config: Config) -> Exercise | None:
    """The exercise a digest for `day` shows.

    That is the one a run already showed that day, whatever has happened to it since; else the
    current exercise, while the user has neither completed nor skipped it; else the next of the
    track whose turn it is. Showing an exercise again costs no model request: its hint was
    written the first time.

    Returns None if it cannot be prepared. That must never cost the digest its news or its
    lesson, so every failure is caught here and logged; nothing is recorded, and the next run
    tries again with the same problem.
    """
    try:
        catalog = load_catalog()
        exercise = (
            restore(catalog, db.leetcode_on(conn, day))
            or restore(catalog, db.active_leetcode(conn))
            or assign(catalog, conn, config.leetcode.rotation)
        )
        place(exercise, db.leetcode_days(conn, exercise.assignment_id) if exercise.assignment_id else [], day)
        exercise.hints_on = hints_enabled(config)
        if exercise.hints_on and not exercise.hint:  # written once: every later showing has it already
            exercise.hint, exercise.hint_source = write_hint(exercise.problem, config)
        return exercise
    except Exception:
        log.exception("could not prepare the LeetCode exercise")
        return None


def place(exercise: Exercise, shown_days: list[str], day: date | None = None) -> None:
    """Say where a showing falls among an exercise's days: when it was first shown, and which day this is.

    `shown_days` are the days it has been shown so far. `day` is the day of the digest being
    written, which counts as one more unless it is among them already.
    """
    days = sorted({*shown_days, day.isoformat()} if day else set(shown_days))
    exercise.assigned_on = days[0] if days else None
    exercise.day = len(days)


def settle(conn, exercise: Exercise) -> Exercise:
    """The exercise a run records, decided once the run's transaction holds the write lock.

    A run chooses its exercise before the minutes of model work, and `dailygrad leetcode mark
    complete` and `next` may be used meanwhile. What they did stands. An exercise the run
    restored has the outcome it has now. An exercise the run chose itself gives way to one that
    `next` assigned in the meantime: the user was shown that one, and recording both would spend
    two turns of the rotation on one request. Choosing is deterministic, so it is normally the
    same problem and only its row is adopted; otherwise the digest shows the user's, with the
    catalog's hint.
    """
    if exercise.assignment_id is not None:
        saved = db.leetcode_by_id(conn, exercise.assignment_id)
        exercise.outcome = saved.outcome if saved else exercise.outcome
        return exercise
    active = restore(load_catalog(), db.active_leetcode(conn))
    if active is None:
        return exercise
    if active.problem.id == exercise.problem.id:
        exercise.assignment_id = active.assignment_id
        return exercise
    log.warning("another exercise was assigned during the run: showing %s, not %s", active.problem.id, exercise.problem.id)
    active.hints_on, active.assigned_on, active.day = exercise.hints_on, exercise.assigned_on, exercise.day
    if active.hints_on and not active.hint:
        active.hint, active.hint_source = active.problem.hints[0], "catalog"
    return active


def assign(catalog: Catalog, conn, rotation: list[str]) -> Exercise:
    """Choose the next exercise from the history alone. Nothing is recorded here.

    The history holds each exercise once, however many days it was shown, so the track whose
    turn it is depends only on how many exercises there have been.
    """
    shown = db.leetcode_history(conn)
    track = track_for_day(rotation, len(shown))
    problem, review = next_problem(catalog.track(track), shown, review_ranks(db.leetcode_progress(conn)))
    log.info("LeetCode exercise %d: %s (%s%s)", len(shown) + 1, problem.id, track, ", review" if review else "")
    return Exercise(problem, track, catalog.sources_of(problem), review)


def review_ranks(progress: dict[str, tuple[str | None, str | None, str | None]]) -> dict[str, int]:
    """How much each problem needs a review, from what the user has said of it: lower needs it more."""
    return {
        problem_id: SOLVED_RANK if solved_at else REVIEW_RANKS.get(confidence, 1)
        for problem_id, (_, confidence, solved_at) in progress.items()
    }


def restore(catalog: Catalog, saved: db.Assigned | None) -> Exercise | None:
    """Rebuild an exercise from its saved row, so that it is shown again unchanged: the same track, review mark and hint.

    Returns None if nothing was saved, or if its problem has since been removed from the catalog.
    """
    if saved is None:
        return None
    problem = catalog.get(saved.problem_id)
    if problem is None:
        return None
    return Exercise(
        problem, saved.track, catalog.sources_of(problem), bool(saved.review), saved.hint or "", saved.hint_source or "",
        assignment_id=saved.id, outcome=saved.outcome,
    )  # fmt: skip


def write_hint(problem: Problem, config: Config) -> tuple[str, str]:
    """The hint a digest shows, and where it came from: "model", or "catalog" if the model was not used.

    The catalog's first hint is the approved material and the fallback. So an exercise always
    has a hint, whatever state Ollama is in.
    """
    if config.leetcode.model_hints and not llm.out_of_time():
        try:
            reply = llm.chat_json(
                config.ollama, HINT_SYSTEM, hint_prompt(problem), HINT_SCHEMA, temperature=HINT_TEMPERATURE
            )
            return parse_hint(reply, problem), "model"
        except llm.LLMError as exc:
            log.warning("using the catalog's own hint for %s: %s", problem.id, exc)
    return problem.hints[0], "catalog"


def hint_prompt(problem: Problem) -> str:
    """The problem and the approved hint. The reference approach is not in it: the model cannot leak what it was not given."""
    return (
        f"Problem: {problem.title}\n"
        f"{problem.statement}\n\n"
        f"Approved hint: {problem.hints[0]}\n\n"
        "Reword the approved hint as JSON."
    )


def parse_hint(reply: dict, problem: Problem) -> str:
    """Validate the hint and flatten it to one line. A hint that would give the approach away is refused."""
    hint = reply.get("hint")
    if not isinstance(hint, str):
        raise llm.LLMError("hint is missing")
    hint = " ".join(hint.split())
    if not MIN_HINT_CHARS <= len(hint) <= MAX_HINT_CHARS:
        raise llm.LLMError(f"hint has an implausible length ({len(hint)} characters)")
    if gives_away(problem, hint):
        raise llm.LLMError("the model's hint would give the approach away")
    return hint


# --- the hint preference


def read_hints(path: Path) -> tuple[bool, str | None]:
    """Whether hints are on, and what is wrong with the preferences file if anything is.

    Without a file hints are on. A file that cannot be understood counts as off: a hint that
    should not have been shown cannot be taken back, while a missing one is one command away.
    """
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return True, None
    except (OSError, ValueError) as exc:
        return False, f"cannot read {path}: {exc}"
    if isinstance(document, dict) and document.get("version") == PREFERENCES_VERSION and type(document.get("hints")) is bool:
        return document["hints"], None
    return False, f"{path} is not a valid LeetCode preferences file"


def hints_enabled(config: Config) -> bool:
    enabled, problem = read_hints(config.leetcode_preferences_path)
    if problem:
        log.warning("%s; showing no hint. `dailygrad leetcode hints on` (or off) replaces the file", problem)
    return enabled


def set_hints(config: Config, enabled: bool) -> bool:
    """Switch hints on or off. Returns whether anything changed. No problem is chosen and no digest is written."""
    path = config.leetcode_preferences_path
    before, problem = read_hints(path)
    if before == enabled and problem is None and path.exists():
        return False
    document = {
        "version": PREFERENCES_VERSION,
        "hints": enabled,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    write_atomic(path, json.dumps(document, indent=2) + "\n")
    return before != enabled or problem is not None
