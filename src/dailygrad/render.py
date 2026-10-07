"""Render the digest as Markdown."""

import re
from datetime import date

from dailygrad.models import Lesson, Story

EVIDENCE_NOTES = {"excerpt": "summarised from the feed excerpt; the full article could not be retrieved"}


def render_digest(day: date, stories: list[Story], failed_sources: list[str], lesson: Lesson | None) -> str:
    """Render the digest. A lesson of None means lesson generation failed this run."""
    lines = [f"# DailyGrad — {day.isoformat()}", "", "## AI News", ""]
    if not stories:
        lines += ["No new stories today.", ""]
    for number, story in enumerate(stories, start=1):
        lines += _story_lines(number, story)
    if failed_sources:
        lines += [f"_Sources unavailable this run: {', '.join(failed_sources)}._", ""]
    lines += _lesson_lines(lesson)
    return "\n".join(lines)


def _lesson_lines(lesson: Lesson | None) -> list[str]:
    lines = ["## AI Micro-Lesson", ""]
    if lesson is None:
        return lines + ["_No lesson today: the local model request failed. The topic will be used in the next run._", ""]
    lines += [f"**{_escape(lesson.topic.title)}**", "", _escape(lesson.text), ""]
    if lesson.recall:
        lines += [f"**Quick recall:** {_escape(lesson.recall.question)}", ""]
    return lines


def _story_lines(number: int, story: Story) -> list[str]:
    candidate = story.candidate
    byline = _escape(candidate.byline)
    if story.evidence in EVIDENCE_NOTES:
        byline += f" ({EVIDENCE_NOTES[story.evidence]})"
    lines = [f"### {number}. [{_escape(candidate.title)}]({_link_target(candidate.url)})", "", f"_{byline}_", ""]
    if story.what_happened:
        lines += [
            f"**What happened:** {_escape(story.what_happened)}",
            "",
            f"**Why it matters:** {_escape(story.why_it_matters)}",
            "",
        ]
    elif story.model_failed:
        lines += ["_Not summarised: the local model request failed. This story may return in a later digest._", ""]
    return lines


def _escape(text: str) -> str:
    """Titles, summaries and lessons are not ours to trust: stop them from adding links, images or formatting."""
    return re.sub(r"([\\\[\]*_`<>])", r"\\\1", text)


def _link_target(url: str) -> str:
    """Percent-encode the characters that would end or corrupt a Markdown link target."""
    for char in "\\ ()":
        url = url.replace(char, f"%{ord(char):02X}")
    return url
