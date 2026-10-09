"""The output files and the latest.json document."""

import json
import os
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from dailygrad import output
from dailygrad.config import Config
from dailygrad.leetcode_catalog import load_catalog
from dailygrad.models import Lesson, Story, Topic

DAY = date(2026, 10, 7)
GENERATED = datetime(2026, 10, 7, 12, 30, 15, 123456, tzinfo=timezone.utc)
TOPIC = Topic("tf-masking", "architectures", "Transformers", 5, "Causal and padding masks", ("a", "b", "c"), "What does the causal mask do?")
OLDER = Topic("nn-backprop", "foundations", "Backpropagation", 1, "Backpropagation", ("a", "b", "c"), "Why is reverse mode efficient?")
KEYS = ["schema_version", "run_id", "date", "generated_at", "status", "model", "stories", "failed_sources", "sources", "lesson", "recall", "leetcode"]
SOURCES = [{"id": "hacker-news", "name": "Hacker News", "group": "community", "enabled": True}]
STORY_KEYS = ["id", "title", "source", "url", "what_happened", "why_it_matters", "evidence", "model_failed"]


def document(stories=(), failed_sources=(), lesson=Lesson(TOPIC, "A lesson.")):
    return output.digest_document(7, DAY, GENERATED, "test-model", list(stories), list(failed_sources), lesson, SOURCES)


def test_document_has_a_fixed_set_of_keys_in_a_fixed_order(make_candidate):
    full = document([Story(make_candidate(), "It happened.", "It matters.", "article")], ["OpenAI"], Lesson(TOPIC, "A lesson.", OLDER))
    empty = document(lesson=None)

    assert list(full) == KEYS and list(empty) == KEYS  # the same keys whether or not there is content
    assert list(full["stories"][0]) == STORY_KEYS
    assert (full["schema_version"], full["run_id"], full["date"], full["model"]) == (1, 7, "2026-10-07", "test-model")
    assert full["generated_at"] == "2026-10-07T12:30:15+00:00"  # whole seconds, with the UTC offset
    assert full["failed_sources"] == ["OpenAI"]
    assert full["sources"] == SOURCES


def test_missing_values_are_null_not_empty_strings(make_candidate):
    headline = document([Story(make_candidate("Only a headline"))])["stories"][0]

    assert (headline["what_happened"], headline["why_it_matters"], headline["evidence"]) == (None, None, None)
    assert headline["model_failed"] is False
    assert document(lesson=None)["lesson"] is None and document(lesson=None)["recall"] is None
    assert document()["recall"] is None  # a lesson without a recall question


def test_story_id_is_the_canonical_url(make_candidate):
    story = Story(make_candidate("Model X", url="https://www.Example.com/model-x/?utm_source=hn#top"))

    assert document([story])["stories"][0]["id"] == "example.com/model-x"
    assert document([story])["stories"][0]["url"] == "https://www.Example.com/model-x/?utm_source=hn#top"


def test_lesson_and_recall_are_serialised():
    result = document(lesson=Lesson(TOPIC, "Masks hide future tokens.", recall=OLDER))

    assert result["lesson"] == {
        "topic_id": "tf-masking",
        "title": "Causal and padding masks",
        "track": "architectures",
        "track_name": "Modern architectures, LLMs and inference",
        "series": "Transformers",
        "lesson": "Masks hide future tokens.",
    }
    assert result["recall"] == {"topic_id": "nn-backprop", "question": "Why is reverse mode efficient?"}


def test_status_is_degraded_when_a_story_or_the_lesson_failed(make_candidate):
    fine = Story(make_candidate("Fine"), "It happened.", "It matters.", "article")
    headline = Story(make_candidate("No article text"))
    failed = Story(make_candidate("Model failed"), model_failed=True)

    assert document([fine, headline])["status"] == "ok"  # a story without article text is not a model failure
    assert document([fine, failed])["status"] == "degraded"
    assert document([fine], lesson=None)["status"] == "degraded"
    assert document([], failed_sources=["OpenAI"])["status"] == "ok"  # a failed source is reported, not degraded


def test_json_text_is_raw_not_markdown_escaped(make_candidate):
    story = Story(make_candidate("Use d_model [now]"), "Uses 4 * d_model.", "It_matters.", "article")

    result = document([story])["stories"][0]

    assert (result["title"], result["what_happened"], result["why_it_matters"]) == ("Use d_model [now]", "Uses 4 * d_model.", "It_matters.")


def test_write_outputs_writes_dated_and_latest_files_with_utf8_json(tmp_path, make_candidate):
    config = Config(data_dir=str(tmp_path / "data"))
    data = document([Story(make_candidate("Café naïve — 模型"), "Résumé.", "✓", "article")])

    output.write_outputs(config, DAY, "# Digest\n", data)

    dated = tmp_path / "data" / "digests" / "2026-10-07.md"
    assert output.dated_markdown_path(config, DAY) == dated
    assert sorted(path.name for path in dated.parent.iterdir()) == ["2026-10-07.json", "2026-10-07.md", "runs"]
    assert dated.read_text(encoding="utf-8") == config.latest_markdown_path.read_text(encoding="utf-8") == "# Digest\n"
    raw = config.latest_json_path.read_bytes()
    assert dated.with_suffix(".json").read_bytes() == raw  # the dated JSON and latest.json are the same document
    assert json.loads(raw.decode("utf-8")) == data
    assert "Café naïve — 模型".encode("utf-8") in raw  # real UTF-8, not \\u escapes
    assert raw.endswith(b"}\n")
    output.write_outputs(config, DAY, "# Digest\n", data)  # rewriting is fine
    assert config.latest_json_path.read_bytes() == raw  # and the same data gives the same bytes


def test_write_atomic_replaces_the_file_and_leaves_no_temporary_file(tmp_path):
    path = tmp_path / "nested" / "latest.md"

    output.write_atomic(path, "first")
    output.write_atomic(path, "second")

    assert path.read_text(encoding="utf-8") == "second"
    assert [entry.name for entry in path.parent.iterdir()] == ["latest.md"]


def test_write_atomic_keeps_the_old_file_if_the_write_fails(tmp_path, monkeypatch):
    path = tmp_path / "latest.json"
    output.write_atomic(path, "the previous, complete file")

    def failing_fsync(descriptor):
        raise OSError("disk full")

    monkeypatch.setattr(os, "fsync", failing_fsync)
    with pytest.raises(OSError, match="disk full"):
        output.write_atomic(path, "a new file that never finished")

    assert path.read_text(encoding="utf-8") == "the previous, complete file"
    assert [entry.name for entry in tmp_path.iterdir()] == ["latest.json"]  # the partial temporary file is removed


def test_write_atomic_never_exposes_a_partial_file(tmp_path, monkeypatch):
    path = tmp_path / "latest.json"
    output.write_atomic(path, "old")
    seen = []
    real_replace = os.replace

    def watching_replace(source, target):
        seen.append((path.read_text(encoding="utf-8"), open(source, encoding="utf-8").read()))
        real_replace(source, target)

    monkeypatch.setattr(os, "replace", watching_replace)
    output.write_atomic(path, "new and complete")

    # Until the rename, the target still holds the old text and the temporary file already holds all of the new text.
    assert seen == [("old", "new and complete")]
    assert path.read_text(encoding="utf-8") == "new and complete"


def test_published_sample_follows_the_documented_layout():
    """examples/sample-digest.json is what integrators copy from, so it must match the contract."""
    examples = Path(__file__).parent.parent / "examples"
    sample = json.loads((examples / "sample-digest.json").read_text(encoding="utf-8"))

    assert list(sample) == KEYS
    assert sample["schema_version"] == output.SCHEMA_VERSION and sample["status"] in ("ok", "degraded")
    assert type(sample["run_id"]) is int and sample["run_id"] >= 1
    assert sample["stories"] and all(list(story) == STORY_KEYS for story in sample["stories"])
    assert sample["sources"] and all(list(source) == ["id", "name", "group", "enabled"] for source in sample["sources"])
    assert list(sample["lesson"]) == ["topic_id", "title", "track", "track_name", "series", "lesson"]
    markdown = (examples / "sample-digest.md").read_text(encoding="utf-8")
    assert all(story["url"] in markdown for story in sample["stories"])
    # The sample's reference answer is the catalog's own for that problem, and only the JSON has it.
    problem = load_catalog().get(sample["leetcode"]["problem_id"])
    assert sample["leetcode"]["reference_solution"] == output.reference_solution(problem)
    assert problem.approach not in markdown
    for private in ("/Users/", "/home/", "localhost"):
        assert private not in markdown and private not in json.dumps(sample)
