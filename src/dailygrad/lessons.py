"""The daily micro-lesson: the model rewrites one curriculum topic into a short refresher.

The facts come from the curriculum. The model's job is wording, not knowledge.
"""

import logging

from dailygrad import curriculum, llm
from dailygrad.config import OllamaConfig
from dailygrad.models import Lesson, Topic

log = logging.getLogger(__name__)

LESSON_TEMPERATURE = 0.0  # a lesson restates vetted facts, so take the model's most likely wording
MIN_LESSON_CHARS = 80
MAX_LESSON_CHARS = 900  # two or three full sentences fit easily; more means the model ran on

LESSON_SYSTEM = """\
You write the daily micro-lesson in a briefing for someone preparing for AI/ML engineering \
interviews. The reader has a computer-science background and has taken an introductory \
deep-learning course, so skip the basics.

You will get one curriculum topic: a title, vetted core points, sometimes a formula, and an \
interview question. Write a micro-lesson of 2 or 3 sentences that would let the reader answer \
that question.

Rules:
- Every statement must restate something in the supplied points or formula. Do not add facts, \
numbers, names, examples or explanations of your own.
- Keep the technical terms, quantities and cause-and-effect exactly as the points give them. Do \
not replace a term with a different one, and do not join two points with "because", "so" or \
"this relies on" unless a point itself states that link.
- Preserve all qualifiers from the curriculum. Never strengthen a claim. Do not turn words such as \
can, may, often, commonly, helps, or tends to into always, requires, eliminates, guarantees, or \
equivalent absolute language.
- Choose the two or three points that best answer the interview question and leave the rest out.
- Start with the key insight, not a textbook definition, and use no filler such as "In this \
lesson" or "It is important to understand".
- Include the formula, a tensor shape or the trade-off when the chosen points contain one.
- Keep each sentence under 35 words. Three plain sentences are better than two long ones.
- Do not repeat the interview question or address the reader.
- Plain sentences only: no lists, headings, Markdown or LaTeX. Write formulas inline as plain text.

Reply with JSON of the form {"lesson": "..."}."""

LESSON_SCHEMA = {
    "type": "object",
    "properties": {"lesson": {"type": "string"}},
    "required": ["lesson"],
}


def build_lesson(topics: list[Topic], history: list[str], recalls: list[str], config: OllamaConfig) -> Lesson | None:
    """Generate the next lesson. Returns None if the model fails, so that the topic is retried next run."""
    topic = curriculum.next_topic(curriculum.build_schedule(topics), history)
    try:
        reply = llm.chat_json(
            config, LESSON_SYSTEM, lesson_prompt(topic), LESSON_SCHEMA, temperature=LESSON_TEMPERATURE
        )
        text = parse_lesson(reply)
    except llm.LLMError as exc:
        log.error("could not generate the lesson on %s: %s", topic.id, exc)
        return None
    log.info("lesson %d: %s", len(history) + 1, topic.id)
    return Lesson(topic, text, recall=curriculum.recall_topic(topics, history, recalls, topic))


def restore_lesson(topics: list[Topic], saved: tuple[str, str, str | None] | None) -> Lesson | None:
    """Rebuild a lesson from its saved row (see db.lesson_on), so that a rerun shows it again unchanged.

    Returns None if nothing was saved, or if its topic has since been removed from the curriculum.
    """
    if saved is None:
        return None
    topic_id, text, recall_id = saved
    by_id = {topic.id: topic for topic in topics}
    if topic_id not in by_id:
        return None
    return Lesson(by_id[topic_id], text, recall=by_id.get(recall_id))


def lesson_prompt(topic: Topic) -> str:
    lines = [
        f"Track: {curriculum.TRACKS[topic.track]}",
        f"Series: {topic.series}, part {topic.part}",
        f"Topic: {topic.title}",
        "",
        "Core points:",
        *(f"- {point}" for point in topic.points),
    ]
    if topic.formula:
        lines += ["", f"Formula: {topic.formula}"]
    lines += ["", f"Interview question: {topic.question}", "", "Write the 2-3 sentence micro-lesson as JSON."]
    return "\n".join(lines)


def parse_lesson(reply: dict) -> str:
    """Validate the lesson and flatten it to one paragraph."""
    lesson = reply.get("lesson")
    if not isinstance(lesson, str):
        raise llm.LLMError("lesson is missing")
    lesson = " ".join(lesson.split())
    if not MIN_LESSON_CHARS <= len(lesson) <= MAX_LESSON_CHARS:
        raise llm.LLMError(f"lesson has an implausible length ({len(lesson)} characters)")
    return lesson
