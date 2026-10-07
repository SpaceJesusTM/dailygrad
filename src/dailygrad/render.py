"""Render the digest as Markdown."""

import re
from datetime import date

from dailygrad.models import Candidate

SCORE_UNITS = {"hackernews": "points", "huggingface": "upvotes"}


def render_digest(day: date, stories: list[Candidate], failed_sources: list[str]) -> str:
    lines = [f"# DailyGrad — {day.isoformat()}", "", "## AI News", ""]
    if stories:
        lines += [f"{number}. {_story_line(story)}" for number, story in enumerate(stories, start=1)]
    else:
        lines.append("No new stories today.")
    if failed_sources:
        lines += ["", f"_Sources unavailable this run: {', '.join(failed_sources)}._"]
    return "\n".join(lines) + "\n"


def _story_line(story: Candidate) -> str:
    detail = story.source
    if story.kind in SCORE_UNITS:
        detail += f", {story.score} {SCORE_UNITS[story.kind]}"
    return f"[{_escape(story.title)}]({_link_target(story.url)}) — {detail}"


def _escape(text: str) -> str:
    """Titles come from the internet: stop them from breaking the link or adding formatting."""
    return re.sub(r"([\\\[\]*_`])", r"\\\1", text)


def _link_target(url: str) -> str:
    """Percent-encode the characters that would end or corrupt a Markdown link target."""
    for char in "\\ ()":
        url = url.replace(char, f"%{ord(char):02X}")
    return url
