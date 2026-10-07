"""The curriculum: loading the knowledge bank, and deciding which topic comes next.

Everything here is deterministic. The order of lessons depends only on the curriculum file
and on the history of lessons already given; the model never chooses a topic.
"""

import re
import tomllib
from collections import Counter
from importlib import resources
from pathlib import Path

from dailygrad.models import Topic

TRACKS = {
    "foundations": "Neural-network and deep-learning foundations",
    "architectures": "Modern architectures, LLMs and inference",
    "agents": "Agentic AI and production AI systems",
}
RUN_LENGTH = 3  # consecutive lessons taken from one series before switching track
RECALL_EVERY = 3  # every third lesson also asks a recall question

ID_PATTERN = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
REQUIRED_FIELDS = {"id": str, "track": str, "series": str, "part": int, "title": str, "points": list, "question": str}
OPTIONAL_FIELDS = {"formula": str}


class CurriculumError(ValueError):
    pass


def load_curriculum(path: Path | None = None) -> list[Topic]:
    """Read and validate the curriculum. Without a path, the file shipped with the package is used."""
    source = path or resources.files("dailygrad") / "curriculum.toml"
    try:
        raw = tomllib.loads(source.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise CurriculumError(f"cannot read curriculum {source}: {exc}") from exc

    entries = raw.get("topic")
    if not isinstance(entries, list) or not entries:
        raise CurriculumError("the curriculum has no [[topic]] entries")
    topics = [_parse_topic(entry, number) for number, entry in enumerate(entries, start=1)]
    _check_ids(topics)
    _check_series(topics)
    return topics


def _parse_topic(entry: dict, number: int) -> Topic:
    where = f"topic {number} ({entry.get('id', 'no id')})"
    for name, kind in REQUIRED_FIELDS.items():
        if type(entry.get(name)) is not kind:
            raise CurriculumError(f"{where}: {name} is missing or is not of type {kind.__name__}")
    for name, value in entry.items():
        if name not in REQUIRED_FIELDS and type(value) is not OPTIONAL_FIELDS.get(name):
            raise CurriculumError(f"{where}: unknown or invalid field {name}")

    if entry["track"] not in TRACKS:
        raise CurriculumError(f"{where}: unknown track {entry['track']}")
    points = entry["points"]
    if not 3 <= len(points) <= 6 or not all(isinstance(point, str) and point.strip() for point in points):
        raise CurriculumError(f"{where}: points must be 3 to 6 non-empty strings")
    if not entry["title"].strip() or not entry["question"].strip().endswith("?"):
        raise CurriculumError(f"{where}: needs a title and a question ending in '?'")
    return Topic(**{**entry, "points": tuple(points)})


def _check_ids(topics: list[Topic]) -> None:
    seen = set()
    for topic in topics:
        if not ID_PATTERN.fullmatch(topic.id):
            raise CurriculumError(f"topic id {topic.id!r} must be lowercase words joined by hyphens")
        if topic.id in seen:
            raise CurriculumError(f"duplicate topic id {topic.id}")
        seen.add(topic.id)


def _check_series(topics: list[Topic]) -> None:
    """A series must be listed in one unbroken block, in one track, with parts numbered 1, 2, 3..."""
    finished, previous = set(), None
    for topic in topics:
        if previous is not None and topic.series == previous.series:
            if topic.track != previous.track:
                raise CurriculumError(f"series {topic.series!r} appears in more than one track")
            expected = previous.part + 1
        else:
            if topic.series in finished:
                raise CurriculumError(f"series {topic.series!r} is not listed in one block")
            finished.add(topic.series)
            expected = 1
        if topic.part != expected:
            raise CurriculumError(f"{topic.id}: expected part {expected} of {topic.series!r}, found part {topic.part}")
        previous = topic


def build_schedule(topics: list[Topic]) -> list[Topic]:
    """Arrange the whole curriculum into the order it is taught in.

    Lessons come in runs: up to RUN_LENGTH consecutive topics of one series, so a subject
    develops over a few days. After each run the next one comes from a different track,
    namely the one that has covered the smallest share of its topics. That keeps the three
    tracks moving at the same relative pace, so none of them goes missing for long, and all
    of them finish together.
    """
    remaining = {track: [topic for topic in topics if topic.track == track] for track in TRACKS}
    totals = {track: len(queue) for track, queue in remaining.items()}

    schedule, last_track = [], None
    while any(remaining.values()):
        waiting = [track for track in TRACKS if remaining[track]]
        choices = [track for track in waiting if track != last_track] or waiting
        track = min(choices, key=lambda name: 1 - len(remaining[name]) / totals[name])

        queue = remaining[track]
        run = [topic for topic in queue[:RUN_LENGTH] if topic.series == queue[0].series]
        schedule += run
        del queue[: len(run)]
        last_track = track
    return schedule


def next_topic(schedule: list[Topic], history: list[str]) -> Topic:
    """The topic for the next lesson, given the IDs of the lessons already given, oldest first.

    It is the first topic in the schedule that has been taught the fewest times. So the first
    pass walks the schedule in order, and once every topic has been taught the walk starts again.
    The previous lesson's topic is never chosen, which only matters after the file is edited.
    """
    last = history[-1] if history else None
    choices = [topic for topic in schedule if topic.id != last] or schedule
    taught = Counter(history)
    fewest = min(taught[topic.id] for topic in choices)
    return next(topic for topic in choices if taught[topic.id] == fewest)


def recall_topic(topics: list[Topic], history: list[str], recalls: list[str], today: Topic) -> Topic | None:
    """The earlier topic whose question is asked alongside today's lesson, or None.

    A question is asked with every RECALL_EVERY-th lesson. It comes from the topic that has
    been asked about least often, and among those the one taught longest ago. Today's topic
    and the previous lesson's topic are too fresh to count as recall.
    """
    lesson_number = len(history) + 1
    if lesson_number % RECALL_EVERY != 0:
        return None

    last_taught = {topic_id: position for position, topic_id in enumerate(history)}
    too_fresh = {today.id, *history[-1:]}
    eligible = [topic for topic in topics if topic.id in last_taught and topic.id not in too_fresh]
    if not eligible:
        return None
    asked = Counter(recalls)
    return min(eligible, key=lambda topic: (asked[topic.id], last_taught[topic.id]))
