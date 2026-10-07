from datetime import date

from dailygrad.render import render_digest

DAY = date(2026, 10, 7)


def test_render_digest(make_candidate):
    stories = [
        make_candidate("Mistral Large 4", url="https://mistral.ai/large-4", score=1677),
        make_candidate("Sparse attention", url="https://arxiv.org/abs/2610.1", kind="huggingface",
                       source="Hugging Face Daily Papers", score=42),
        make_candidate("Model X", url="https://lab.example/x", kind="rss", source="Lab Blog", score=0),
    ]  # fmt: skip

    assert render_digest(DAY, stories, failed_sources=[]) == (
        "# DailyGrad — 2026-10-07\n"
        "\n"
        "## AI News\n"
        "\n"
        "1. [Mistral Large 4](https://mistral.ai/large-4) — Hacker News, 1677 points\n"
        "2. [Sparse attention](https://arxiv.org/abs/2610.1) — Hugging Face Daily Papers, 42 upvotes\n"
        "3. [Model X](https://lab.example/x) — Lab Blog\n"
    )


def test_render_empty_digest_and_failed_sources():
    digest = render_digest(DAY, [], failed_sources=["OpenAI", "Hacker News"])

    assert "No new stories today." in digest
    assert digest.endswith("_Sources unavailable this run: OpenAI, Hacker News._\n")


def test_render_escapes_untrusted_titles_and_urls(make_candidate):
    story = make_candidate("[RFC] *bold* claims](https://evil.example)", url="https://example.com/a_(b) c/\\")

    digest = render_digest(DAY, [story], failed_sources=[])

    assert r"[\[RFC\] \*bold\* claims\](https://evil.example)](https://example.com/a_%28b%29%20c/%5C)" in digest
