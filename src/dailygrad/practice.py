"""Practice modes: which LeetCode problem becomes the next exercise, from which sources, and how far practice has come.

The question sources are the catalog's tracks (neetcode-150, amd, vanguard). The selected ones
make one pool: every problem any of them lists, once, however many lists it is on. The pool
is ordered as the catalog introduces problems (easy to hard, topic by topic), and a problem
keeps every list it is on for reporting. The mode decides what comes next from that pool:

    coverage  every problem once, in the pool's order, then "coverage complete". Every exercise
              since the current pass began counts, whatever chose it; history from before
              practice modes is the first pass. A fresh pass is started only on request.
    loop      every problem once per cycle, in an order shuffled when the cycle begins and
              stored, then a new cycle, reshuffled, and so on. A cycle always holds the whole
              combined pool. If the selected sources change, the open cycle ends unfinished and
              the next exercise starts a new one on the new pool.
    learning  a problem completed once comes back for review `review_interval_days` after its
              latest completion, up to `max_reviews` reviews (or without limit). Due reviews
              come first, the longest due first; then problems never completed. With neither,
              practice waits: "No reviews due. Next review: ...".

Each question is decided from its current practice period alone. `dailygrad leetcode practice
restart-questions` resets the questions of a scope (every question, the named sources' or the
selected sources'): they are eligible again in every mode, as if never practised (coverage
assigns them again, learning counts no earlier completion or review of them), while every
earlier exercise, outcome and mark stays in the database for the record, and questions outside
the scope are untouched. A reset of every question also begins a new practice session, in
which coverage passes and loop cycles are counted from 1. The exercise in progress at a reset
counts as its question's first in the new period, so finishing it does not bring it straight
back. Whether a problem was ever assigned before ("first" or "repeat") is still said of all
history.

A loop cycle always holds the whole combined pool. A reset that covers every question of the
open cycle ends it, and the next exercise begins a freshly shuffled one. A narrower reset keeps
the cycle: the questions of its scope the cycle has assigned already go back into its unassigned
part, in the cycle's stored order, and are given again before it ends; nothing outside the
scope is repeated, and the problem just assigned is never given straight back.

Everything here is deterministic except the order of a new loop cycle, which is shuffled once
and stored. Only the user's word moves practice on: an exercise ends when they complete or
skip it (tutor.py), never because it was shown, a hint was asked for or time passed. A
skipped problem is set aside for one review interval in learning mode, so `next` cannot
bring it straight back, and a skipped review is not a completed one.

Days are calendar days in the local time zone, the one that dates the digest (America/Toronto
on a host set to it). Functions that need "today" are given it, so tests control the clock.

The settings come from [leetcode] in the config file, overridden by what `dailygrad leetcode
practice set` stored in <data_dir>/leetcode_practice.json. That file is runtime data, like
the hint preference: Git never touches it and an update leaves it alone. The scheduler's own
state (passes, cycles, why each exercise was chosen) is in the database, beside the history.
"""

import json
import logging
import random
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from dailygrad import db
from dailygrad.config import (
    LEETCODE_TRACKS, MAX_INTERVAL_DAYS, MAX_REVIEWS, PRACTICE_MODES, UNLIMITED, Config, valid_interval,
    valid_max_reviews,
)  # fmt: skip
from dailygrad.leetcode_catalog import Catalog
from dailygrad.models import Problem
from dailygrad.output import write_atomic
from dailygrad.preferences import locked

log = logging.getLogger(__name__)

VERSION = 1
SETTINGS = ("sources", "mode", "review_interval_days", "max_reviews")
ALL = "all"  # every source, in `practice set --sources all`
ENCOUNTERS = ("first", "repeat", "review")
WAITING_STATES = ("coverage_complete", "caught_up", "learning_complete")
RECOVERY = "`dailygrad leetcode practice set` (or `practice reset`) replaces it"

shuffler = random.Random()  # the one source of randomness: a new loop cycle's order. Tests seed it.


class PracticeError(Exception):
    """A request that was refused, or a settings file that cannot be used. Nothing was changed."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Settings:
    sources: tuple[str, ...]  # the selected sources, in the catalog's order
    mode: str
    review_interval_days: int
    max_reviews: int | None  # None: no limit
    origin: dict = field(default_factory=dict, compare=False)  # each setting: "preferences" or "config"

    def document(self) -> dict:
        return {
            "sources": list(self.sources),
            "mode": self.mode,
            "review_interval_days": self.review_interval_days,
            "max_reviews": UNLIMITED if self.max_reviews is None else self.max_reviews,
        }


# --- settings


def read_overrides(path) -> dict:
    """The settings stored by `practice set`, as {setting: value}. A missing file stores none.

    Raises PracticeError for a file that exists but cannot be read or understood. A source the
    catalog no longer has is dropped; if none is left, the file cannot be used.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeDecodeError) as exc:
        raise PracticeError("invalid_preferences", f"cannot read {path}: {exc}; {RECOVERY}") from exc
    try:
        document = json.loads(text)
    except ValueError:
        document = None
    if isinstance(document, dict) and document.get("version") == VERSION and set(document) <= {*SETTINGS, "version", "updated_at"}:
        stored = {name: document[name] for name in SETTINGS if name in document}
        sources = stored.get("sources", list(LEETCODE_TRACKS))
        if isinstance(sources, list) and all(isinstance(source, str) for source in sources):
            if "sources" in stored:
                stored["sources"] = [source for source in LEETCODE_TRACKS if source in sources]
            if _valid(stored):
                return stored
    raise PracticeError("invalid_preferences", f"{path} is not a valid LeetCode practice settings file; {RECOVERY}")


def _valid(stored: dict) -> bool:
    """Whether every stored setting is one a config file could hold."""
    return (
        stored.get("sources", [None]) != []
        and stored.get("mode", PRACTICE_MODES[0]) in PRACTICE_MODES
        and valid_interval(stored.get("review_interval_days", 1))
        and valid_max_reviews(stored.get("max_reviews", 1))
    )


def _combine(config: Config, stored: dict) -> Settings:
    defaults = {
        "sources": config.leetcode.sources,
        "mode": config.leetcode.mode,
        "review_interval_days": config.leetcode.review_interval_days,
        "max_reviews": config.leetcode.max_reviews,
    }
    values = defaults | stored
    return Settings(
        sources=tuple(source for source in LEETCODE_TRACKS if source in values["sources"]),
        mode=values["mode"],
        review_interval_days=values["review_interval_days"],
        max_reviews=None if values["max_reviews"] == UNLIMITED else values["max_reviews"],
        origin={name: "preferences" if name in stored else "config" for name in SETTINGS},
    )


def settings(config: Config) -> Settings:
    """The settings in force: the config file's, overridden by those stored with `practice set`.

    Raises PracticeError if the settings file exists but cannot be used. Nothing is guessed in
    its place: a guess could practise from sources the user switched away from.
    """
    return _combine(config, read_overrides(config.practice_preferences_path))


def settings_or_defaults(config: Config) -> tuple[Settings, str | None]:
    """The settings in force, for reading only: with a settings file that cannot be used, the config
    file's, and the problem with the file. Never use this to choose an exercise: see settings()."""
    try:
        return settings(config), None
    except PracticeError as exc:
        return _combine(config, {}), str(exc)


def parse_changes(sources=None, mode=None, interval=None, max_reviews=None) -> dict:
    """Validate requested changes, as given on a command line. Raises PracticeError; nothing is stored here."""
    changes = {}
    if sources is not None:
        names = [str(name).strip().lower() for name in sources]
        unknown = [name for name in names if name != ALL and name not in LEETCODE_TRACKS]
        if unknown:
            known = ", ".join([*LEETCODE_TRACKS, ALL])
            raise PracticeError("unknown_source", f"unknown question source: {', '.join(unknown)[:200]} (known: {known})")
        chosen = LEETCODE_TRACKS if ALL in names else [source for source in LEETCODE_TRACKS if source in names]
        if not chosen:
            raise PracticeError("no_sources", "at least one question source must be selected")
        changes["sources"] = list(chosen)
    if mode is not None:
        if mode not in PRACTICE_MODES:
            raise PracticeError("unknown_mode", f"unknown practice mode: {str(mode)[:40]} (known: {', '.join(PRACTICE_MODES)})")
        changes["mode"] = mode
    if interval is not None:
        days = _whole_number(interval)
        if not valid_interval(days):
            raise PracticeError("bad_interval", f"the review interval must be a whole number of days from 1 to {MAX_INTERVAL_DAYS}")
        changes["review_interval_days"] = days
    if max_reviews is not None:
        limit = UNLIMITED if str(max_reviews).strip().lower() == UNLIMITED else _whole_number(max_reviews)
        if not valid_max_reviews(limit):
            raise PracticeError("bad_max_reviews", f'the maximum number of reviews must be from 1 to {MAX_REVIEWS}, or "{UNLIMITED}"')
        changes["max_reviews"] = limit
    if not changes:
        raise PracticeError("nothing_to_change", "name at least one setting to change: sources, mode, interval or max reviews")
    return changes


def _whole_number(value) -> int | None:
    if type(value) is int:
        return value
    text = str(value).strip()
    return int(text) if text.isdigit() and len(text) <= 6 else None


def change(config: Config, changes: dict, now: datetime | None = None) -> dict:
    """Store validated changes (see parse_changes) over those already stored. Returns the settings now in force.

    The exercise in progress is never replaced: the settings apply when the next one is chosen.
    A settings file that cannot be read is replaced, keeping only these changes; the result
    says so. Two changes at once are serialised by a lock, so neither loses the other's.
    """
    now = now or datetime.now(timezone.utc)
    path = config.practice_preferences_path
    with locked(path):
        try:
            stored, damaged = read_overrides(path), False
        except PracticeError:
            stored, damaged = {}, True
        before = None if damaged else _combine(config, stored)
        updated = stored | changes
        after = _combine(config, updated)
        if damaged or updated != stored:
            _write(path, updated, now)
    return {
        "ok": True,
        "action": "set",
        "changed": before != after,
        "replaced_damaged_file": damaged,
        "previous": before.document() if before else None,
        "settings": after.document(),
        "from": after.origin,
        "applies": "to the next exercise chosen; the current exercise stays until you complete or skip it",
        "preferences_file": str(path.resolve()),
    }


def reset(config: Config) -> dict:
    """Forget the settings stored by `practice set`: the config file's apply again. History is not touched."""
    path = config.practice_preferences_path
    with locked(path):
        try:
            before = _combine(config, read_overrides(path))
        except PracticeError:
            before = None
        existed = path.exists()
        path.unlink(missing_ok=True)
    after = _combine(config, {})
    return {
        "ok": True,
        "action": "reset",
        "changed": existed and before != after,
        "removed_file": existed,
        "settings": after.document(),
        "from": after.origin,
        "preferences_file": str(path.resolve()),
    }


def _write(path, stored: dict, now: datetime) -> None:
    document = {"version": VERSION, **{name: stored[name] for name in SETTINGS if name in stored}}
    document["updated_at"] = now.isoformat(timespec="seconds")
    write_atomic(path, json.dumps(document, indent=2) + "\n")


# --- the state the modes read


@dataclass
class Snapshot:
    """Every exercise with its outcome and schedule, the loop cycles, the coverage passes and the resets."""

    history: list[db.Scheduled] = field(default_factory=list)
    cycles: list[db.Cycle] = field(default_factory=list)
    passes: list[tuple[str, int]] = field(default_factory=list)
    resets: list[db.Reset] = field(default_factory=list)

    @property
    def everything_reset(self) -> db.Reset | None:
        """The newest reset of every question: the one the practice session in force began with."""
        return next((reset for reset in reversed(self.resets) if reset.problems is None), None)

    @property
    def start(self) -> int:
        """The exercise ID the practice session in force begins after: 0 for the first session."""
        reset = self.everything_reset
        return reset.after_assignment_id if reset else 0

    @property
    def epoch(self) -> int:
        """The practice period in force, from 1: one more for each reset, whatever its scope."""
        return len(self.resets) + 1

    def reset_point(self, problem_id: str, before: int | None = None) -> int:
        """The exercise ID a question's current practice period begins after: its exercises up to it no longer count.

        With `before`, only the resets made before that exercise was assigned count: its period then.
        """
        return max(
            (
                reset.after_assignment_id for reset in self.resets
                if (reset.problems is None or problem_id in reset.problems)
                and (before is None or reset.after_assignment_id < before)
            ),
            default=0,
        )  # fmt: skip

    def session(self) -> "Snapshot":
        """What the modes decide from: each question's exercises in its current period, and the session's cycles and passes."""
        if not self.resets:
            return self
        everything = self.everything_reset
        after, after_cycle = (everything.after_assignment_id, everything.after_cycle_id) if everything else (0, 0)
        return Snapshot(
            [entry for entry in self.history if entry.id > self.reset_point(entry.problem_id)],
            [cycle for cycle in self.cycles if cycle.id > after_cycle],
            [started for started in self.passes if started[1] > after],
            self.resets,
        )


def snapshot(conn: sqlite3.Connection) -> Snapshot:
    return Snapshot(db.scheduled_history(conn), db.cycles(conn), db.coverage_passes(conn), db.practice_resets(conn))


def local_day(stamp: str) -> date:
    """The local calendar day of a stored time: the day it was, where the digest is dated."""
    return datetime.fromisoformat(stamp).astimezone().date()


def day_text(day: date) -> str:
    return f"{day:%B} {day.day}"


def source_names(catalog: Catalog, sources) -> str:
    return " + ".join(catalog.sources[source].name for source in sources)


@dataclass
class Choice:
    """The next exercise, and why: what is recorded for it in leetcode_schedule."""

    problem: Problem
    mode: str
    sources: tuple[str, ...]
    encounter: str  # "first", "repeat" or "review"
    cycle: db.Cycle | None = None  # loop mode
    position: int | None = None  # loop mode: its place in the cycle, from 1
    review_number: int | None = None  # learning mode, a review: 1 for the first
    due_on: str | None = None  # learning mode, a review: the day it became due

    @property
    def track(self) -> str:
        """The selected source it is drawn from, for leetcode_assignments.track: the first that lists it."""
        return next(source for source in self.sources if source in self.problem.tracks)


@dataclass(frozen=True)
class Waiting:
    """No problem can be assigned now. Not a failure: the digest says so and is not degraded."""

    mode: str
    sources: tuple[str, ...]
    state: str  # "coverage_complete", "caught_up" or "learning_complete"
    next_review_on: str | None = None  # caught up: the first day something is eligible again
    max_reviews: int | None = None

    def message(self, catalog: Catalog) -> str:
        names = source_names(catalog, self.sources)
        if self.state == "coverage_complete":
            return f"{names} coverage complete."
        if self.state == "caught_up":
            return f"No reviews due. Next review: {day_text(date.fromisoformat(self.next_review_on))}."
        return f"{names}: every question has had its {self.max_reviews} review{'' if self.max_reviews == 1 else 's'}. No reviews are left."


def choose(catalog: Catalog, current: Settings, state: Snapshot, today: date, skip: frozenset = frozenset()) -> Choice | Waiting | None:
    """The next exercise under the settings, or why there is none, from the whole snapshot. Reads only.

    None in loop mode means a new cycle has to begin first (start_cycle). `skip` holds problems
    to leave out, such as the one still in progress when status looks ahead.
    """
    pool = [problem for problem in catalog.pool(current.sources) if problem.id not in skip]
    assigned = {entry.problem_id for entry in state.history}  # in any practice period
    last = state.history[-1].problem_id if state.history else None
    encounter = lambda problem: "repeat" if problem.id in assigned else "first"  # noqa: E731
    state = state.session()
    if current.mode == "coverage":
        after = state.passes[-1][1] if state.passes else state.start
        encountered = {entry.problem_id for entry in state.history if entry.id > after}
        waiting = _not_straight_back([problem for problem in pool if problem.id not in encountered], last)
        if waiting:
            return Choice(waiting[0], "coverage", current.sources, encounter(waiting[0]))
        return Waiting("coverage", current.sources, "coverage_complete")
    if current.mode == "loop":
        cycle, remaining, done = _open_cycle(catalog, current, state)
        remaining = [problem_id for problem_id in remaining if problem_id not in skip]
        if not remaining:
            return None
        problem = catalog.get(_not_straight_back(remaining, last, key=lambda problem_id: problem_id)[0])
        return Choice(problem, "loop", current.sources, encounter(problem), cycle=cycle, position=done + 1)
    return _learning_choice(pool, current, state, today, encounter, last)


def _not_straight_back(candidates: list, last: str | None, key=lambda problem: problem.id) -> list:
    """The candidates in order, but not beginning with the problem assigned last while another is left.

    Only a reset (or a fresh coverage pass) can make the problem just assigned a candidate again:
    it is given after the next one, never twice in a row.
    """
    if len(candidates) > 1 and key(candidates[0]) == last:
        return [candidates[1], candidates[0], *candidates[2:]]
    return candidates


def _open_cycle(catalog: Catalog, current: Settings, state: Snapshot) -> tuple[db.Cycle | None, list[str], int]:
    """(the open cycle, its problems not yet assigned in it in order, how many have been).

    Nothing remains of a cycle whose sources are no longer the selected ones: it is not continued.
    A question reset since the cycle assigned it counts as not assigned in it (see the module's note).
    """
    cycle = next((cycle for cycle in reversed(state.cycles) if cycle.ended is None), None)
    if cycle is None or set(cycle.sources) != set(current.sources):
        return cycle, [], 0
    done = {entry.problem_id for entry in state.history if entry.cycle_id == cycle.id}
    return cycle, [problem_id for problem_id in cycle.problems if problem_id not in done and catalog.get(problem_id)], len(done)


def start_cycle(conn: sqlite3.Connection, catalog: Catalog, current: Settings, state: Snapshot, now: datetime) -> bool:
    """In loop mode, begin a new cycle if the next exercise needs one. Returns whether it did.

    Call it inside a write transaction, with the whole snapshot. An open cycle that is finished,
    or whose sources are no longer the selected ones, is ended first; its exercises stay as they
    are. The new order is shuffled once and stored, so a restart never reshuffles it. Where the
    pool allows, it does not begin with the problem assigned last, so no problem is given twice
    in a row, even across a new practice session. Cycles are numbered from 1 in each session.
    """
    session = state.session()
    cycle, remaining, _ = _open_cycle(catalog, current, session)
    if current.mode != "loop" or remaining:
        return False
    if cycle is not None:
        finished = set(cycle.sources) == set(current.sources)
        db.end_cycle(conn, cycle.id, "completed" if finished else "sources_changed", now)
    order = [problem.id for problem in catalog.pool(current.sources)]
    shuffler.shuffle(order)
    last = state.history[-1].problem_id if state.history else None
    if len(order) > 1 and order[0] == last:
        swap = shuffler.randrange(1, len(order))
        order[0], order[swap] = order[swap], order[0]
    number = max((cycle.number for cycle in session.cycles), default=0) + 1
    db.start_cycle(conn, number, current.sources, order, now)
    log.info("LeetCode loop cycle %d begins: %d problems from %s", number, len(order), ", ".join(current.sources))
    return True


def next_exercise(conn: sqlite3.Connection, catalog: Catalog, current: Settings, today: date, now: datetime) -> Choice | Waiting:
    """The next exercise, beginning a loop cycle first if one is needed. Call it inside a write transaction."""
    state = snapshot(conn)
    if start_cycle(conn, catalog, current, state, now):
        state = snapshot(conn)
    return choose(catalog, current, state, today)


def record(conn: sqlite3.Connection, assignment_id: int, choice: Choice, now: datetime) -> None:
    db.record_schedule(
        conn, assignment_id, choice.mode, choice.sources, choice.encounter, choice.cycle.id if choice.cycle else None,
        choice.review_number, choice.due_on, now,
    )  # fmt: skip


# --- learning mode


@dataclass
class _Record:
    """What learning mode knows of one problem."""

    completed_on: list[date] = field(default_factory=list)  # local days, oldest first
    reviews: int = 0  # completed learning-mode reviews
    last_completed_id: int = 0
    skipped_on: date | None = None  # the day it was last skipped
    skipped_id: int = 0


def _records(session: Snapshot) -> dict[str, _Record]:
    """What learning mode knows of each problem, from the practice session in force alone."""
    records = {}
    for entry in session.history:
        record = records.setdefault(entry.problem_id, _Record())
        if entry.outcome == "completed":
            record.completed_on.append(local_day(entry.closed_at))
            record.last_completed_id = entry.id
            # A review chosen in an earlier session and completed in this one is this session's first completion.
            record.reviews += entry.encounter == "review" and len(record.completed_on) > 1
        elif entry.outcome == "skipped":
            record.skipped_on, record.skipped_id = local_day(entry.closed_at), entry.id
    return records


def _schedule(record: _Record | None, current: Settings) -> tuple[str, date | None, date | None]:
    """(where the problem stands, the day it is next eligible, the day its review fell due).

    Stands "new" (never completed), "review" (a review is or will be due) or "retired" (all its
    reviews are done). A problem skipped since its latest completion is set aside for one interval.
    """
    interval = timedelta(days=current.review_interval_days)
    if record is None:
        return "new", None, None
    deferred = record.skipped_on + interval if record.skipped_on and record.skipped_id > record.last_completed_id else None
    if not record.completed_on:
        return "new", deferred, None
    if current.max_reviews is not None and record.reviews >= current.max_reviews:
        return "retired", None, None
    due = record.completed_on[-1] + interval
    return "review", max(due, deferred) if deferred else due, due


def _learning_choice(
    pool: list[Problem], current: Settings, state: Snapshot, today: date, encounter, last: str | None = None
) -> Choice | Waiting:  # fmt: skip
    records = _records(state)
    offered = {entry.problem_id for entry in state.history}
    reviews, new, later = [], [], []
    for index, problem in enumerate(pool):
        record = records.get(problem.id)
        stands, eligible_on, due = _schedule(record, current)
        if stands == "retired":
            continue
        if eligible_on is not None and eligible_on > today:
            later.append(eligible_on)
        elif stands == "review":
            reviews.append((eligible_on, due, index, problem))
        else:
            new.append((problem.id in offered, index, problem))
    if reviews:  # the longest due first; then the order of the pool
        _, due, _, problem = min(reviews, key=lambda review: review[:3])
        number = records[problem.id].reviews + 1
        return Choice(problem, "learning", current.sources, "review", review_number=number, due_on=due.isoformat())
    if new:  # never offered before, in the pool's order, ahead of those offered and not completed
        problem = _not_straight_back([candidate[2] for candidate in sorted(new, key=lambda candidate: candidate[:2])], last)[0]
        return Choice(problem, "learning", current.sources, encounter(problem))
    if later:
        return Waiting("learning", current.sources, "caught_up", min(later).isoformat())
    return Waiting("learning", current.sources, "learning_complete", max_reviews=current.max_reviews)


# --- resetting questions


@dataclass(frozen=True)
class Scope:
    """The questions a reset covers: every one, or those of some sources (named, or the ones selected)."""

    kind: str  # "all", "sources" or "selected"
    sources: tuple[str, ...]  # every source for "all"; in the catalog's order

    def problems(self, catalog: Catalog) -> list[str] | None:
        """The questions covered, each once however many of its sources list it; None for every question."""
        return None if self.kind == "all" else [problem.id for problem in catalog.pool(self.sources)]


def parse_scope(config: Config, everything: bool = False, sources=None, selected: bool = False) -> Scope:
    """Exactly one scope, as given on a command line. Raises PracticeError; nothing is stored here."""
    if sum((bool(everything), sources is not None, bool(selected))) != 1:
        raise PracticeError("no_scope", "name exactly one scope: --all, --sources ID... or --selected")
    if everything:
        return Scope("all", tuple(LEETCODE_TRACKS))
    if selected:
        return Scope("selected", settings(config).sources)  # an unusable settings file raises: nothing is guessed
    return Scope("sources", tuple(parse_changes(sources=sources)["sources"]))


@dataclass(frozen=True)
class ResetPlan:
    """What a reset made now would do."""

    after: int  # each covered question's exercises up to this one end their period; the one in progress is kept
    freed: int  # exercises that would stop counting: none means the reset would change nothing
    questions: int  # questions covered, each once
    cycle: db.Cycle | None  # the open loop cycle, if any
    cycle_ends: bool  # the reset covers all of it: it ends, and the next loop exercise begins a fresh one
    reopened: int  # otherwise: questions the cycle had assigned that it will give again


def plan_reset(catalog: Catalog, state: Snapshot, scope: Scope, active: db.Assigned | None) -> ResetPlan:
    """What resetting `scope` now would do. Reads only. The exercise in progress counts as its question's first after it."""
    problems = scope.problems(catalog)
    covered = (lambda problem_id: True) if problems is None else frozenset(problems).__contains__
    newest = state.history[-1].id if state.history else 0
    after = active.id - 1 if active else newest
    session = state.session()
    freed = [entry for entry in session.history if covered(entry.problem_id) and entry.id <= after]
    cycle = next((cycle for cycle in reversed(session.cycles) if cycle.ended is None), None)
    ends = cycle is not None and all(covered(problem_id) for problem_id in cycle.problems)
    reopened = len({entry.problem_id for entry in freed if cycle and entry.cycle_id == cycle.id}) if not ends else 0
    return ResetPlan(after, len(freed), len(catalog.problems) if problems is None else len(problems), cycle, ends, reopened)


def reset_questions(
    conn: sqlite3.Connection, catalog: Catalog, scope: Scope, active: db.Assigned | None, now: datetime
) -> ResetPlan:  # fmt: skip
    """Reset the questions of `scope`, if that changes anything. Call it inside a write transaction.

    Only a reset row is added, and the open loop cycle is ended if the reset covers all of it.
    """
    plan = plan_reset(catalog, snapshot(conn), scope, active)
    if plan.freed:
        sources = None if scope.kind == "all" else scope.sources
        db.record_reset(conn, plan.after, scope.kind, sources, scope.problems(catalog), now)
        if plan.cycle_ends:
            db.end_cycle(conn, plan.cycle.id, "reset", now)
        log.info("LeetCode questions reset (%s: %s): %d exercises no longer count", scope.kind, ", ".join(scope.sources), plan.freed)
    return plan


def reset_document(catalog: Catalog, reset: db.Reset) -> dict:
    """A reset as the commands report it."""
    return {
        "scope": reset.scope,
        "sources": [source for source in (reset.sources or LEETCODE_TRACKS) if source in catalog.sources],
        "questions": len(catalog.problems) if reset.problems is None else len(reset.problems),
        "reset_at": reset.reset_at,
    }


# --- describing practice


def describe(catalog: Catalog, state: Snapshot, assignment_id: int, current: Settings | None) -> dict | None:
    """Why an exercise was chosen, as a digest and the commands show it. None for one from before practice modes."""
    entry = next((entry for entry in state.history if entry.id == assignment_id), None)
    if entry is None or entry.mode is None:
        return None
    cycle = next((cycle for cycle in state.cycles if cycle.id == entry.cycle_id), None)
    position = len({
        other.problem_id for other in state.history
        if other.cycle_id == entry.cycle_id and state.reset_point(other.problem_id, before=entry.id) < other.id <= entry.id
    })  # its place among the cycle's questions as it stood then, a question reset and given again counted once
    return _document(entry.mode, entry.sources, entry.encounter, cycle, position, entry.review_number, entry.due_on, current)


def choice_document(choice: Choice, current: Settings | None) -> dict:
    """What describe will say of a choice once it is recorded."""
    return _document(
        choice.mode, choice.sources, choice.encounter, choice.cycle, choice.position, choice.review_number,
        choice.due_on, current,
    )  # fmt: skip


def _document(mode, sources, encounter, cycle, position, review_number, due_on, current) -> dict:
    limit = None if current is None else current.max_reviews
    return {
        "mode": mode,
        "sources": list(sources),  # selected when it was chosen; `sources` of the exercise lists every one it is on
        "encounter": encounter,  # "first", "repeat" or "review"
        "cycle": {"number": cycle.number, "position": position, "size": len(cycle.problems)} if cycle else None,
        "review": {"number": review_number, "limit": UNLIMITED if limit is None else limit, "due_on": due_on}
        if encounter == "review" else None,
    }  # fmt: skip


def status_document(catalog: Catalog, current: Settings, waiting: Waiting | None) -> dict:
    """The digest's `leetcode_practice`: the settings in force and, when nothing could be assigned, why."""
    mode, sources = (waiting.mode, waiting.sources) if waiting else (current.mode, current.sources)
    return {
        "mode": mode,
        "sources": [{"id": source, "name": catalog.sources[source].name} for source in sources],
        "state": waiting.state if waiting else "exercise",
        "message": waiting.message(catalog) if waiting else None,
        "next_review_on": waiting.next_review_on if waiting else None,
    }


def overview(catalog: Catalog, current: Settings, everything: Snapshot, today: date, active: db.Assigned | None) -> dict:
    """How far practice has come in each mode in the session in force, and what the next exercise will be. Reads only."""
    state = everything.session()
    newest = everything.resets[-1] if everything.resets else None
    began = everything.everything_reset
    session = {
        "epoch": everything.epoch,  # the practice period: 1 until the first `restart-questions`, one more for each
        "started_at": began.reset_at if began else None,  # the session: since the newest reset of every question
        "last_reset": reset_document(catalog, newest) if newest else None,
        "exercises": sum(entry.id > newest.after_assignment_id for entry in everything.history) if newest
        else len(everything.history),  # assigned since the newest reset, the one in progress included
    }
    pool = catalog.pool(current.sources)
    ids = {problem.id for problem in pool}
    after = state.passes[-1][1] if state.passes else state.start
    encountered = {entry.problem_id for entry in state.history if entry.id > after} & ids
    coverage = {
        "pass": len(state.passes) + 1,  # counted in the session
        "pass_started_at": state.passes[-1][0] if state.passes else session["started_at"],
        "pool": len(pool),
        "encountered": len(encountered),
        "remaining": len(pool) - len(encountered),
        "complete": len(encountered) == len(pool),
        "by_source": [
            {
                "id": source, "name": catalog.sources[source].name,
                "problems": sum(source in problem.tracks for problem in pool),
                "encountered": sum(source in problem.tracks for problem in pool if problem.id in encountered),
            }
            for source in current.sources
        ],
    }  # fmt: skip

    open_cycle = next((cycle for cycle in reversed(state.cycles) if cycle.ended is None), None)
    cycle = None
    if open_cycle is not None:
        done = {entry.problem_id for entry in state.history if entry.cycle_id == open_cycle.id}
        cycle = {
            "number": open_cycle.number,
            "sources": list(open_cycle.sources),
            "size": len(open_cycle.problems),
            "assigned": len(done),
            "remaining": len(open_cycle.problems) - len(done),
            "started_at": open_cycle.started_at,
            "matches_selection": set(open_cycle.sources) == set(current.sources),
        }
    loop = {"cycle": cycle, "cycles_completed": sum(cycle.ended == "completed" for cycle in state.cycles)}

    records = _records(state)
    counts = dict.fromkeys(("due_now", "new_remaining", "scheduled", "reviews_complete"), 0)
    upcoming_reviews = []
    for problem in pool:
        stands, eligible_on, _ = _schedule(records.get(problem.id), current)
        if stands == "retired":
            counts["reviews_complete"] += 1
        elif stands == "new":
            counts["new_remaining"] += 1
        elif eligible_on <= today:
            counts["due_now"] += 1
        else:
            counts["scheduled"] += 1
            upcoming_reviews.append(eligible_on)
    learning = {
        **counts,
        "next_review_on": min(upcoming_reviews).isoformat() if upcoming_reviews else None,
        "review_interval_days": current.review_interval_days,
        "max_reviews": UNLIMITED if current.max_reviews is None else current.max_reviews,
    }

    skip = frozenset({active.problem_id}) if active else frozenset()
    following = choose(catalog, current, everything, today, skip)
    if following is None:
        upcoming = {"state": "new_cycle", "message": "A new loop cycle, freshly shuffled, begins with the next exercise.",
                    "next_review_on": None}  # fmt: skip
    elif isinstance(following, Waiting):
        upcoming = {"state": following.state, "message": following.message(catalog), "next_review_on": following.next_review_on}
    else:
        upcoming = {"state": "exercise", "message": None, "next_review_on": None}
    return {"session": session, "coverage": coverage, "loop": loop, "learning": learning, "upcoming": upcoming}
