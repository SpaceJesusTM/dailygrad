"""The LeetCode catalog: loading the question bank, and deciding which problem comes next.

Everything here is deterministic. Which problem a day gets depends only on the catalog file,
the rotation and the history of problems already shown; the model never chooses a problem.

The catalog is a snapshot made during development from three sources (see docs/leetcode.md).
A run reads only the packaged file: it never contacts LeetCode or any of the sources.
"""

import re
import tomllib
from collections import Counter
from dataclasses import dataclass
from datetime import date
from importlib import resources
from pathlib import Path

from dailygrad.config import LEETCODE_TRACKS
from dailygrad.models import Problem, Source

# Topics in the order they are introduced. A track walks them in this order once per difficulty.
CATEGORIES = {
    "arrays-hashing": "Arrays & Hashing",
    "two-pointers": "Two Pointers",
    "sliding-window": "Sliding Window",
    "stack": "Stack",
    "binary-search": "Binary Search",
    "linked-list": "Linked List",
    "trees": "Trees",
    "tries": "Tries",
    "heap": "Heap / Priority Queue",
    "backtracking": "Backtracking",
    "graphs": "Graphs",
    "advanced-graphs": "Advanced Graphs",
    "dp-1d": "1-D Dynamic Programming",
    "dp-2d": "2-D Dynamic Programming",
    "greedy": "Greedy",
    "intervals": "Intervals",
    "math-geometry": "Math & Geometry",
    "bit-manipulation": "Bit Manipulation",
}
DIFFICULTIES = ("easy", "medium", "hard")  # the order a track introduces them in
# What every exercise asks. The answers are the reader's to work out, so none is given.
PROMPTS = (
    "What data structure would you choose?",
    "How would your algorithm work at a high level?",
    "What would its time complexity be?",
    "What would its space complexity be?",
    "What edge cases should you consider?",
)
SOURCE_KINDS = ("curriculum", "company")

ID_PATTERN = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
COMPLEXITY = re.compile(r"O\(.+\)")
STATED_COMPLEXITY = re.compile(r"\bO\s*\(")  # a hint must not give a complexity away
REQUIRED_FIELDS = {
    "id": str, "number": int, "title": str, "difficulty": str, "category": str, "tracks": list,
    "statement": str, "input": str, "output": str, "constraints": list, "hints": list, "spoilers": list,
    "approach": str, "time": str, "space": str, "edge_cases": list,
}  # fmt: skip
OPTIONAL_FIELDS = {"premium": bool}
LIST_SIZES = {"constraints": (1, 4), "hints": (1, 3), "spoilers": (1, 8), "edge_cases": (1, 4)}
MAX_STATEMENT_CHARS = 420  # a digest shows it whole, so it has to stay short
MAX_HINT_CHARS = 220
SOURCE_FIELDS = {"id": str, "name": str, "kind": str, "publisher": str, "url": str, "retrieved": str, "problems": int}


class CatalogError(ValueError):
    pass


@dataclass(frozen=True)
class Catalog:
    snapshot: str  # the day the sources were read and checked, YYYY-MM-DD
    sources: dict[str, Source]  # by track ID
    problems: tuple[Problem, ...]

    def get(self, problem_id: str | None) -> Problem | None:
        return next((problem for problem in self.problems if problem.id == problem_id), None)

    def sources_of(self, problem: Problem) -> tuple[Source, ...]:
        return tuple(self.sources[track] for track in problem.tracks)

    def track(self, track: str) -> list[Problem]:
        """A track's problems in the order they are first shown.

        Easy problems come first, then medium, then hard. Within a difficulty the topics follow
        CATEGORIES, so each pass revisits the topics in the same order at a higher level.
        """
        members = [problem for problem in self.problems if track in problem.tracks]
        topics = list(CATEGORIES)
        return sorted(members, key=lambda p: (DIFFICULTIES.index(p.difficulty), topics.index(p.category)))


def load_catalog(path: Path | None = None) -> Catalog:
    """Read and validate the catalog. Without a path, the file shipped with the package is used."""
    source = path or resources.files("dailygrad") / "leetcode.toml"
    try:
        raw = tomllib.loads(source.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise CatalogError(f"cannot read the LeetCode catalog {source}: {exc}") from exc

    snapshot = raw.get("catalog", {}).get("snapshot") if isinstance(raw.get("catalog"), dict) else None
    if not _is_date(snapshot):
        raise CatalogError("the catalog needs [catalog] snapshot = \"YYYY-MM-DD\"")
    sources = _parse_sources(raw.get("source"))
    entries = raw.get("problem")
    if not isinstance(entries, list) or not entries:
        raise CatalogError("the catalog has no [[problem]] entries")
    problems = tuple(_parse_problem(entry, number) for number, entry in enumerate(entries, start=1))
    _check_unique(problems)
    for track, declared in sources.items():
        found = sum(track in problem.tracks for problem in problems)
        if found != declared.problems:
            raise CatalogError(f"source {track} lists {declared.problems} problems but the catalog holds {found}")
    return Catalog(snapshot, sources, problems)


def _is_date(value) -> bool:
    try:
        return isinstance(value, str) and date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _parse_sources(entries) -> dict[str, Source]:
    if not isinstance(entries, list):
        raise CatalogError("the catalog has no [[source]] entries")
    sources = {}
    for entry in entries:
        where = f"source {entry.get('id', 'without an id')}" if isinstance(entry, dict) else "a source"
        if not isinstance(entry, dict) or set(entry) != set(SOURCE_FIELDS):
            raise CatalogError(f"{where}: needs exactly the fields {', '.join(SOURCE_FIELDS)}")
        for name, kind in SOURCE_FIELDS.items():
            if type(entry[name]) is not kind:
                raise CatalogError(f"{where}: {name} is not of type {kind.__name__}")
        if entry["kind"] not in SOURCE_KINDS or not _is_date(entry["retrieved"]) or not entry["url"].startswith("https://"):
            raise CatalogError(f"{where}: needs a kind of {' or '.join(SOURCE_KINDS)}, an https url and a retrieved date")
        if entry["id"] in sources:
            raise CatalogError(f"duplicate source {entry['id']}")
        sources[entry["id"]] = Source(**entry)
    if tuple(sources) != LEETCODE_TRACKS:
        raise CatalogError(f"the sources must be exactly: {', '.join(LEETCODE_TRACKS)}")
    return sources


def _parse_problem(entry: dict, number: int) -> Problem:
    where = f"problem {number} ({entry.get('id', 'no id')})"
    for name, kind in REQUIRED_FIELDS.items():
        if type(entry.get(name)) is not kind:
            raise CatalogError(f"{where}: {name} is missing or is not of type {kind.__name__}")
    for name, value in entry.items():
        if name not in REQUIRED_FIELDS and type(value) is not OPTIONAL_FIELDS.get(name):
            raise CatalogError(f"{where}: unknown or invalid field {name}")
    for name, kind in REQUIRED_FIELDS.items():
        if kind is str and not entry[name].strip():
            raise CatalogError(f"{where}: {name} is empty")
    for name, (fewest, most) in LIST_SIZES.items():
        values = entry[name]
        if not fewest <= len(values) <= most or not all(isinstance(value, str) and value.strip() for value in values):
            raise CatalogError(f"{where}: {name} must be {fewest} to {most} non-empty strings")

    if not ID_PATTERN.fullmatch(entry["id"]) or entry["number"] < 1:
        raise CatalogError(f"{where}: needs a LeetCode slug as its id and a positive number")
    if entry["difficulty"] not in DIFFICULTIES or entry["category"] not in CATEGORIES:
        raise CatalogError(f"{where}: unknown difficulty or category")
    tracks = entry["tracks"]
    if not tracks or len(set(tracks)) != len(tracks) or not all(track in LEETCODE_TRACKS for track in tracks):
        raise CatalogError(f"{where}: tracks must name one or more of {', '.join(LEETCODE_TRACKS)}, each once")
    if len(entry["statement"]) > MAX_STATEMENT_CHARS or any(len(hint) > MAX_HINT_CHARS for hint in entry["hints"]):
        raise CatalogError(f"{where}: the statement or a hint is too long")
    if any("`" in entry[name] or "\n" in entry[name] for name in ("input", "output")):
        raise CatalogError(f"{where}: the example must be plain single lines")  # it is shown as inline code
    if not COMPLEXITY.fullmatch(entry["time"]) or not COMPLEXITY.fullmatch(entry["space"]):
        raise CatalogError(f"{where}: time and space must be written like O(n)")

    problem = Problem(
        id=entry["id"], number=entry["number"], title=entry["title"], difficulty=entry["difficulty"],
        category=entry["category"], tracks=tuple(tracks), statement=entry["statement"],
        example_input=entry["input"], example_output=entry["output"], constraints=tuple(entry["constraints"]),
        hints=tuple(entry["hints"]), spoilers=tuple(entry["spoilers"]), approach=entry["approach"],
        time=entry["time"], space=entry["space"], edge_cases=tuple(entry["edge_cases"]),
        premium=entry.get("premium", False),
    )  # fmt: skip
    # What a digest shows must not give the approach away: the statement and the first hint.
    for label, text in (("statement", problem.statement), ("first hint", problem.hints[0])):
        if spoiler := spoiler_in(problem, text):
            raise CatalogError(f"{where}: the {label} contains the spoiler {spoiler!r}")
    if any(STATED_COMPLEXITY.search(hint) for hint in problem.hints):
        raise CatalogError(f"{where}: a hint states a complexity")
    return problem


def _check_unique(problems: tuple[Problem, ...]) -> None:
    """A problem listed by several sources is one entry with several tracks, never two entries."""
    for field in ("id", "number", "title"):
        counts = Counter(getattr(problem, field) for problem in problems)
        repeated = [str(value) for value, count in counts.items() if count > 1]
        if repeated:
            raise CatalogError(f"duplicate problem {field}: {', '.join(repeated)}")


def spoiler_in(problem: Problem, text: str, already_said: str = "") -> str | None:
    """The first of the problem's spoilers that `text` contains, or None.

    A spoiler matches at the start of a word, in any case, so "hash" also catches "hashing"
    and "hash map". That errs toward calling a hint a giveaway, which only costs a rewording.
    A spoiler that `already_said` contains is not one: repeating a reader's own word reveals nothing.
    """
    lowered, known = text.casefold(), already_said.casefold()
    for spoiler in problem.spoilers:
        term = spoiler.casefold()
        if term not in known and re.search(rf"(?<![a-z0-9]){re.escape(term)}", lowered):
            return spoiler
    return None


def gives_away(problem: Problem, text: str) -> bool:
    """Whether generated text would reveal the approach: a spoiler, a stated complexity, or code."""
    return bool(spoiler_in(problem, text)) or bool(STATED_COMPLEXITY.search(text)) or "```" in text


def track_for_day(rotation: list[str], days_assigned: int) -> str:
    """The track whose turn it is, given how many days have already been assigned an exercise.

    The rotation advances with each exercise shown, not with the calendar, so a day on which
    DailyGrad did not run does not skip a track.
    """
    return rotation[days_assigned % len(rotation)]


def next_problem(order: list[Problem], shown: list[str], review_rank: dict[str, int] | None = None) -> tuple[Problem, bool]:
    """The next problem of a track, and whether it is a review.

    `order` is the track's problems as Catalog.track gives them, and `shown` the IDs of every
    problem shown so far on any track, oldest first. The first problem not yet shown anywhere
    is next, so a problem that another track already used is not repeated while new ones remain.

    Once the whole track has been shown, the day is a review: the problem shown least often,
    and among those the one the user ranked most in need of it (`review_rank`, lower first),
    then the one shown longest ago. The track therefore never loses its day, and nothing in
    the history is removed to make a problem available again.
    """
    seen = set(shown)
    for problem in order:
        if problem.id not in seen:
            return problem, False

    times = Counter(shown)
    last_shown = {problem_id: position for position, problem_id in enumerate(shown)}
    ranks = review_rank or {}
    choices = [problem for problem in order if problem.id != shown[-1]] or order  # not yesterday's again
    problem = min(choices, key=lambda p: (times[p.id], ranks.get(p.id, 1), last_shown[p.id]))
    return problem, True
