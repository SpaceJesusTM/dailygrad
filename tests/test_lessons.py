"""Lesson generation, with the model faked."""

import logging

import pytest

from dailygrad import lessons, llm
from dailygrad.config import OllamaConfig
from dailygrad.curriculum import build_schedule
from dailygrad.models import Lesson, Topic

CONFIG = OllamaConfig()
LESSON_TEXT = "Dividing the scores by sqrt(d_k) keeps their variance near 1. Without it softmax saturates and gradients shrink."

ATTENTION = Topic(
    id="tf-scaled-attention",
    track="architectures",
    series="Transformers",
    part=1,
    title="Scaled dot-product attention",
    points=("Scores are Q K^T.", "They are divided by sqrt(d_k).", "Unscaled scores saturate softmax."),
    question="Why is attention scaled by the square root of the key dimension?",
    formula="softmax(Q K^T / sqrt(d_k)) V",
)
MASKS = Topic("tf-masking", "architectures", "Transformers", 2, "Causal masks", ("a", "b", "c"), "What does the causal mask do?")
BLOCK = Topic("tf-block", "architectures", "Transformers", 3, "The block", ("a", "b", "c"), "What is in a block?")
TOPICS = [ATTENTION, MASKS, BLOCK]


@pytest.fixture
def model(monkeypatch):
    """Replace llm.chat_json. Set model.reply to a dict, or to an exception to raise."""

    def chat_json(config, system, prompt, schema, temperature=None):
        chat_json.calls.append({"system": system, "prompt": prompt, "schema": schema, "temperature": temperature})
        if isinstance(chat_json.reply, Exception):
            raise chat_json.reply
        return chat_json.reply

    chat_json.calls = []
    chat_json.reply = {"lesson": LESSON_TEXT}
    monkeypatch.setattr(llm, "chat_json", chat_json)
    return chat_json


def test_lesson_prompt_supplies_the_vetted_material():
    assert lessons.lesson_prompt(ATTENTION) == (
        "Track: Modern architectures, LLMs and inference\n"
        "Series: Transformers, part 1\n"
        "Topic: Scaled dot-product attention\n"
        "\n"
        "Core points:\n"
        "- Scores are Q K^T.\n"
        "- They are divided by sqrt(d_k).\n"
        "- Unscaled scores saturate softmax.\n"
        "\n"
        "Formula: softmax(Q K^T / sqrt(d_k)) V\n"
        "\n"
        "Interview question: Why is attention scaled by the square root of the key dimension?\n"
        "\n"
        "Write the 2-3 sentence micro-lesson as JSON."
    )
    assert "Formula" not in lessons.lesson_prompt(MASKS)  # optional field


def test_system_prompt_restricts_the_model_to_the_supplied_facts():
    system = lessons.LESSON_SYSTEM

    assert "2 or 3 sentences" in system
    assert "Every statement must restate something in the supplied points or formula" in system
    assert "Do not add facts" in system
    assert "preparing for AI/ML engineering interviews" in system


def test_system_prompt_forbids_strengthening_claims():
    assert (
        "Preserve all qualifiers from the curriculum. Never strengthen a claim. Do not turn words such as "
        "can, may, often, commonly, helps, or tends to into always, requires, eliminates, guarantees, or "
        "equivalent absolute language."
    ) in lessons.LESSON_SYSTEM


def test_lessons_are_generated_at_temperature_zero(model):
    config = OllamaConfig(temperature=0.7)  # whatever the configured temperature is

    lessons.build_lesson(TOPICS, history=[], recalls=[], config=config)

    assert lessons.LESSON_TEMPERATURE == 0
    assert model.calls[0]["temperature"] == 0
    assert config.temperature == 0.7  # the setting used for news is not changed


def test_build_lesson_generates_the_next_topic(model):
    lesson = lessons.build_lesson(TOPICS, history=[], recalls=[], config=CONFIG)

    assert lesson == Lesson(ATTENTION, LESSON_TEXT, recall=None)
    (call,) = model.calls
    assert call["schema"] == lessons.LESSON_SCHEMA
    assert call["system"] == lessons.LESSON_SYSTEM
    assert call["prompt"] == lessons.lesson_prompt(ATTENTION)


def test_build_lesson_follows_the_schedule_and_adds_recall_when_due(model):
    second = lessons.build_lesson(TOPICS, history=[ATTENTION.id], recalls=[], config=CONFIG)
    third = lessons.build_lesson(TOPICS, history=[ATTENTION.id, MASKS.id], recalls=[], config=CONFIG)

    assert (second.topic, second.recall) == (MASKS, None)
    assert (third.topic, third.recall) == (BLOCK, ATTENTION)
    assert [topic.id for topic in build_schedule(TOPICS)] == [ATTENTION.id, MASKS.id, BLOCK.id]


@pytest.mark.parametrize(
    "reply",
    [
        llm.LLMError("cannot reach Ollama"),
        {},
        {"lesson": None},
        {"lesson": ["a", "list"]},
        {"lesson": "   "},
        {"lesson": "Too short."},
        {"lesson": "word " * 400},
    ],
)
def test_build_lesson_returns_none_when_generation_fails(model, reply, caplog):
    model.reply = reply

    with caplog.at_level(logging.ERROR):
        assert lessons.build_lesson(TOPICS, history=[], recalls=[], config=CONFIG) is None

    assert "could not generate the lesson on tf-scaled-attention" in caplog.text


def test_parse_lesson_flattens_whitespace():
    reply = {"lesson": "  Dividing the scores by sqrt(d_k) keeps their variance near 1.\n\n  Without it,   softmax saturates.  "}

    assert lessons.parse_lesson(reply) == (
        "Dividing the scores by sqrt(d_k) keeps their variance near 1. Without it, softmax saturates."
    )


def test_restore_lesson_rebuilds_a_saved_lesson():
    assert lessons.restore_lesson(TOPICS, None) is None
    assert lessons.restore_lesson(TOPICS, ("tf-masking", "Saved text.", None)) == Lesson(MASKS, "Saved text.")
    assert lessons.restore_lesson(TOPICS, ("tf-block", "Saved text.", "tf-scaled-attention")) == Lesson(
        BLOCK, "Saved text.", recall=ATTENTION
    )


def test_restore_lesson_gives_up_if_the_topic_left_the_curriculum():
    assert lessons.restore_lesson(TOPICS, ("removed-topic", "Saved text.", None)) is None
    # A recall topic that was removed just drops the question.
    assert lessons.restore_lesson(TOPICS, ("tf-block", "Saved text.", "removed-topic")) == Lesson(BLOCK, "Saved text.")
