from datetime import date

from dailygrad.models import Lesson, Story, Topic
from dailygrad.render import render_digest

DAY = date(2026, 10, 7)
TOPIC = Topic("tf-scaled-attention", "architectures", "Transformers", 4, "Scaled dot-product attention", ("a", "b", "c"),
              "Why is attention scaled by the square root of the key dimension?")  # fmt: skip
OLDER = Topic("inf-kv-cache", "architectures", "Inference", 1, "The KV cache", ("a", "b", "c"), "What is stored in the KV cache?")
LESSON = Lesson(TOPIC, "Scores are divided by sqrt(d_k). That keeps softmax out of saturation.")
LESSON_SECTION = (
    "## AI Micro-Lesson\n"
    "\n"
    "**Scaled dot-product attention**\n"
    "\n"
    "Scores are divided by sqrt(d\\_k). That keeps softmax out of saturation.\n"
)


def test_render_digest(make_candidate):
    stories = [
        Story(
            make_candidate("Mistral Large 4", url="https://mistral.ai/large-4", score=1677),
            "Mistral released Large 4.",
            "It runs on one GPU.",
            "article",
        ),
        Story(
            make_candidate("Model X", url="https://lab.example/x", kind="rss", source="Lab Blog", score=0),
            "The lab announced Model X.",
            "Details are thin.",
            "excerpt",
        ),
        Story(make_candidate("Sparse attention", url="https://arxiv.org/abs/2610.1", kind="huggingface",
                             source="Hugging Face Daily Papers", score=42)),
    ]  # fmt: skip

    assert render_digest(DAY, stories, failed_sources=[], lesson=LESSON) == (
        "# DailyGrad — 2026-10-07\n"
        "\n"
        "## AI News\n"
        "\n"
        "### 1. [Mistral Large 4](https://mistral.ai/large-4)\n"
        "\n"
        "_Hacker News, 1677 points_\n"
        "\n"
        "**What happened:** Mistral released Large 4.\n"
        "\n"
        "**Why it matters:** It runs on one GPU.\n"
        "\n"
        "### 2. [Model X](https://lab.example/x)\n"
        "\n"
        "_Lab Blog (summarised from the feed excerpt; the full article could not be retrieved)_\n"
        "\n"
        "**What happened:** The lab announced Model X.\n"
        "\n"
        "**Why it matters:** Details are thin.\n"
        "\n"
        "### 3. [Sparse attention](https://arxiv.org/abs/2610.1)\n"
        "\n"
        "_Hugging Face Daily Papers, 42 upvotes_\n"
        "\n" + LESSON_SECTION
    )


def test_render_empty_digest_and_failed_sources():
    digest = render_digest(DAY, [], failed_sources=["OpenAI", "Hacker News"], lesson=LESSON)

    assert digest == (
        "# DailyGrad — 2026-10-07\n"
        "\n"
        "## AI News\n"
        "\n"
        "No new stories today.\n"
        "\n"
        "_Sources unavailable this run: OpenAI, Hacker News._\n"
        "\n" + LESSON_SECTION
    )


def test_render_marks_stories_the_model_failed_on(make_candidate):
    stories = [
        Story(make_candidate("Model failed"), model_failed=True),
        Story(make_candidate("No article text")),
        Story(make_candidate("Summarised"), "It happened.", "It matters.", "article"),
    ]

    digest = render_digest(DAY, stories, failed_sources=[], lesson=LESSON)

    note = "_Not summarised: the local model request failed. This story may return in a later digest._"
    assert digest.count(note) == 1
    assert digest.index("Model failed") < digest.index(note) < digest.index("No article text")


def test_render_escapes_untrusted_titles_and_urls(make_candidate):
    story = Story(make_candidate("[RFC] *bold* claims](https://evil.example)", url="https://example.com/a_(b) c/\\"))

    digest = render_digest(DAY, [story], failed_sources=[], lesson=LESSON)

    assert r"[\[RFC\] \*bold\* claims\](https://evil.example)](https://example.com/a_%28b%29%20c/%5C)" in digest


def test_render_escapes_model_output(make_candidate):
    """A summary steered by a hostile article must not be able to add links, images or HTML."""
    story = Story(
        make_candidate(),
        "Click [here](https://evil.example) ![x](https://evil.example/pixel.png)",
        "<img src=x onerror=alert(1)>",
        "article",
    )

    digest = render_digest(DAY, [story], failed_sources=[], lesson=LESSON)

    assert r"Click \[here\](https://evil.example) !\[x\](https://evil.example/pixel.png)" in digest
    assert r"\<img src=x onerror=alert(1)\>" in digest


def test_render_lesson_with_a_recall_question():
    lesson = Lesson(TOPIC, LESSON.text, recall=OLDER)

    digest = render_digest(DAY, [], failed_sources=[], lesson=lesson)

    assert digest.endswith(LESSON_SECTION + "\n**Quick recall:** What is stored in the KV cache?\n")
    assert "Why is attention scaled" not in digest  # today's own question is kept for a later recall


def test_render_says_so_when_the_lesson_failed(make_candidate):
    story = Story(make_candidate("Model X"), "It happened.", "It matters.", "article")

    digest = render_digest(DAY, [story], failed_sources=[], lesson=None)

    assert "**What happened:** It happened." in digest  # the news is unaffected
    assert digest.endswith(
        "## AI Micro-Lesson\n"
        "\n"
        "_No lesson today: the local model request failed. The topic will be used in the next run._\n"
    )


def test_render_escapes_the_lesson_text():
    lesson = Lesson(TOPIC, "See [this](https://evil.example) and use W*x with d_model.", recall=None)

    digest = render_digest(DAY, [], failed_sources=[], lesson=lesson)

    assert r"See \[this\](https://evil.example) and use W\*x with d\_model." in digest
