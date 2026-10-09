"""The daily LeetCode exercise: its hint, the hint preference, and its place in a run and in the outputs."""

import json
import os
import sqlite3
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
import requests

from conftest import NOW
from dailygrad import cli, db, history, leetcode, llm, output, pipeline, render, tutor
from dailygrad.config import Config, ConfigError, load_config
from dailygrad.leetcode_catalog import CATEGORIES, PROMPTS, CatalogError, gives_away, load_catalog
from dailygrad.models import Exercise
from test_pipeline import FEED, SCHEDULE, FakeModel, day, fake_articles, fake_web, lesson_text, read_latest, table_count  # noqa: F401 (fixtures)

CATALOG = load_catalog()
NEETCODE, AMD, VANGUARD = (CATALOG.track(track) for track in ("neetcode-150", "amd", "vanguard"))
FIRST = NEETCODE[0]  # contains-duplicate
MODEL_HINT = "Consider what you would want to keep in mind about the values you have already passed."
EARLIER_KEYS = ["schema_version", "run_id", "date", "generated_at", "status", "model", "stories", "failed_sources", "sources", "lesson", "recall"]
PUBLIC_KEYS = [
    "problem_id", "number", "title", "url", "difficulty", "premium", "track", "review", "sources", "company_tags",
    "statement", "example", "constraints", "prompts", "hints_enabled", "hint", "hint_source",
    "exercise_id", "assigned_on", "day", "is_carryover", "awaiting_completion",
]  # fmt: skip
DOCUMENT_KEYS = [*PUBLIC_KEYS, "reference_solution"]  # what a digest shows, then the answer for a program that tutors
REFERENCE_KEYS = ["source", "complete", "topic", "approach", "time", "space", "edge_cases"]


class Tutor(FakeModel):
    """The fake model of test_pipeline, which can also word a hint."""

    def __init__(self):
        super().__init__()
        self.hint_reply = {"hint": MODEL_HINT}
        self.hint_error = None  # set to an exception to make only the hint request fail
        self.hint_requests = []  # (system, prompt, temperature) of each

    def chat_json(self, config, system, prompt, schema, temperature=None):
        if schema is not leetcode.HINT_SCHEMA:
            return super().chat_json(config, system, prompt, schema, temperature)
        if self.error:
            raise self.error
        self.hint_requests.append((system, prompt, temperature))
        if self.hint_error:
            raise self.hint_error
        return self.hint_reply


@pytest.fixture
def config(tmp_path):
    config = Config(data_dir=str(tmp_path / "data"))
    config.rss.feeds = [FEED]
    config.final_story_count = 3
    return config  # LeetCode exercises are on, as they are by default


@pytest.fixture
def model(monkeypatch):
    model = Tutor()
    monkeypatch.setattr(llm, "chat_json", model.chat_json)
    monkeypatch.setattr(llm, "unload", model.unload)
    return model


def assignments(config):
    conn = sqlite3.connect(config.db_path)
    rows = conn.execute("SELECT problem_id, track, review, hint, hint_source FROM leetcode_assignments ORDER BY id").fetchall()
    conn.close()
    return rows


def exercise_of(problem, track=None, **fields):
    return Exercise(problem, track or problem.tracks[0], CATALOG.sources_of(problem), **fields)


def practise(config, days, start=0):
    """Run on `days` consecutive days, completing each day's exercise, so that every day brings a new one."""
    for number in range(start, start + days):
        pipeline.run(config, now=day(number))
        tutor.complete(config, now=day(number))


# --- in a run


def test_a_run_adds_the_exercise_after_the_news_and_the_lesson(config, fake_web, model, fake_articles):
    digest, model_ok = pipeline.run(config, now=NOW)

    assert model_ok
    assert digest.index("## AI News") < digest.index("## AI Micro-Lesson") < digest.index("## LeetCode Micro-Lesson")
    assert f"**[{FIRST.title}]({FIRST.url})**" in digest and FIRST.statement in digest
    assert f"**Hint:** {MODEL_HINT}" in digest
    assert digest.endswith("_No implementation required: describe your approach in words._\n")
    assert assignments(config) == [(FIRST.id, "neetcode-150", 0, MODEL_HINT, "model")]


def test_the_json_document_gains_a_leetcode_field(config, fake_web, model, fake_articles):
    pipeline.run(config, now=NOW)

    document = read_latest(config)
    assert document["status"] == "ok" and document["schema_version"] == 1
    assert document["leetcode"] == {
        "problem_id": "contains-duplicate",
        "number": 217,
        "title": "Contains Duplicate",
        "url": "https://leetcode.com/problems/contains-duplicate/",
        "difficulty": "easy",
        "premium": False,
        "track": "neetcode-150",
        "review": False,
        "sources": [{"id": "neetcode-150", "name": "NeetCode 150", "kind": "curriculum", "publisher": "NeetCode"}],
        "company_tags": [],
        "statement": FIRST.statement,
        "example": {"input": "nums = [1, 2, 3, 1]", "output": "true"},
        "constraints": ["1 ≤ n ≤ 10^5"],
        "prompts": list(PROMPTS),
        "hints_enabled": True,
        "hint": MODEL_HINT,
        "hint_source": "model",
        "exercise_id": 1,
        "assigned_on": NOW.astimezone().date().isoformat(),
        "day": 1,
        "is_carryover": False,
        "awaiting_completion": True,
        "reference_solution": {
            "source": "catalog",
            "complete": True,
            "topic": "Arrays & Hashing",
            "approach": FIRST.approach,
            "time": "O(n)",
            "space": "O(n)",
            "edge_cases": ["a single element", "all values distinct", "negative values"],
        },
    }


def test_the_reference_answer_is_only_in_the_json_key_made_for_it(config, fake_web, model, fake_articles):
    for number in range(6):
        digest, _ = pipeline.run(config, now=day(number))
        document = read_latest(config)
        problem = CATALOG.get(document["leetcode"]["problem_id"])
        exercise = dict(document["leetcode"])
        reference = exercise.pop("reference_solution")
        shown = digest + json.dumps(document | {"leetcode": exercise}, ensure_ascii=False)  # all but that one key

        assert list(document["leetcode"]) == DOCUMENT_KEYS and list(exercise) == PUBLIC_KEYS
        assert problem.approach not in shown and not any(case in shown for case in problem.edge_cases)
        assert f"Time: {problem.time}" not in shown and CATEGORIES[problem.category] not in shown
        assert problem.category not in json.dumps(exercise)
        assert (reference["approach"], reference["time"], reference["space"]) == (problem.approach, problem.time, problem.space)
        # The firmer hints and the spoiler words are for DailyGrad's own hints and checks: they are in neither.
        assert problem.hints[1] not in digest + json.dumps(document, ensure_ascii=False)
        assert "spoilers" not in json.dumps(document) and "hints" not in reference
        tutor.complete(config, now=day(number))  # so that the next day brings another problem
    assert len(assignments(config)) == 6


def test_the_reference_answer_is_in_every_json_output_and_in_no_markdown(config, fake_web, model, fake_articles):
    pipeline.run(config, now=NOW)
    (run,) = history.archived_runs(config)
    dated = config.digest_dir / f"{NOW.astimezone().date().isoformat()}.json"

    for path in (config.latest_json_path, dated, Path(run["json"])):
        reference = json.loads(path.read_text(encoding="utf-8"))["leetcode"]["reference_solution"]
        assert list(reference) == REFERENCE_KEYS and reference["approach"] == FIRST.approach
    for path in (config.latest_markdown_path, dated.with_suffix(".md"), Path(run["markdown"])):
        markdown = path.read_text(encoding="utf-8")
        assert FIRST.approach not in markdown and "reference" not in markdown.lower()
        assert not any(case in markdown for case in FIRST.edge_cases)


def test_the_reference_answer_does_not_depend_on_the_hint_preference_or_the_model(config, fake_web, model, fake_articles):
    leetcode.set_hints(config, False)
    model.error = llm.LLMError("cannot reach Ollama at http://localhost:11434")

    pipeline.run(config, now=NOW)

    exercise = read_latest(config)["leetcode"]
    assert (exercise["hints_enabled"], exercise["hint"]) == (False, None)  # no hint is shown...
    assert exercise["reference_solution"]["approach"] == FIRST.approach  # ...and the catalog's answer is still there
    assert model.hint_requests == []  # it comes from the catalog: no model request is made for it


def test_a_rerun_carries_the_same_reference_answer(config, fake_web, model, fake_articles):
    pipeline.run(config, now=NOW)
    first = read_latest(config)["leetcode"]["reference_solution"]

    pipeline.run(config, now=NOW)

    assert read_latest(config)["leetcode"]["reference_solution"] == first


def test_completed_exercises_rotate_through_neetcode_amd_and_vanguard(config, fake_web, model, fake_articles):
    practise(config, 7)

    assert [(problem, track) for problem, track, _, _, _ in assignments(config)] == [
        (NEETCODE[0].id, "neetcode-150"),
        (AMD[0].id, "amd"),  # two-sum, which NeetCode 150 also lists
        (VANGUARD[0].id, "vanguard"),
        (NEETCODE[1].id, "neetcode-150"),
        (AMD[1].id, "amd"),
        (VANGUARD[1].id, "vanguard"),
        (NEETCODE[3].id, "neetcode-150"),  # NEETCODE[2] is two-sum: already shown on AMD's turn
    ]
    assert NEETCODE[2].id == AMD[0].id == "two-sum"


def test_a_company_exercise_credits_the_tag_to_the_third_party(config, fake_web, model, fake_articles):
    practise(config, 1)
    digest, _ = pipeline.run(config, now=day(1))

    exercise = read_latest(config)["leetcode"]
    assert (exercise["problem_id"], exercise["track"]) == ("two-sum", "amd")
    assert exercise["company_tags"] == ["AMD"]
    assert exercise["sources"] == [
        {"id": "neetcode-150", "name": "NeetCode 150", "kind": "curriculum", "publisher": "NeetCode"},
        {"id": "amd", "name": "AMD", "kind": "company", "publisher": "Interview Solver"},
    ]
    assert "_Easy · Source: NeetCode 150, AMD (Interview Solver tag)_" in digest


def test_a_rerun_on_the_same_day_shows_the_same_exercise_and_asks_the_model_nothing_more(config, fake_web, model, fake_articles):
    pipeline.run(config, now=NOW)
    first = read_latest(config)["leetcode"]
    model.hint_reply = {"hint": "A different wording that the rerun must not adopt, however good it is."}

    pipeline.run(config, now=NOW)
    pipeline.run(config, now=NOW)

    assert read_latest(config)["leetcode"] == first
    assert len(model.hint_requests) == 1 and len(assignments(config)) == 1
    assert table_count(config, "runs") == 3  # each run is still recorded; only the exercise is reused


def test_the_day_after_a_completion_takes_the_next_track(config, fake_web, model, fake_articles):
    pipeline.run(config, now=day(0))
    pipeline.run(config, now=day(0))
    tutor.complete(config, now=day(0))
    pipeline.run(config, now=day(1))

    assert [problem for problem, _, _, _, _ in assignments(config)] == [FIRST.id, "two-sum"]
    assert read_latest(config)["leetcode"]["track"] == "amd"


def test_days_without_a_run_neither_skip_a_track_nor_end_the_exercise(config, fake_web, model, fake_articles):
    pipeline.run(config, now=day(0))
    pipeline.run(config, now=day(5))  # four days missed: still the first exercise
    assert [track for _, track, _, _, _ in assignments(config)] == ["neetcode-150"]

    tutor.complete(config, now=day(5))
    pipeline.run(config, now=day(9))  # three more missed: the next track, not the one after
    assert [track for _, track, _, _, _ in assignments(config)] == ["neetcode-150", "amd"]


def test_history_survives_a_restart(config, fake_web, model, fake_articles):
    practise(config, 3)

    conn = db.connect(config.db_path)  # a fresh connection, as a new process would open
    assert db.leetcode_history(conn) == [NEETCODE[0].id, AMD[0].id, VANGUARD[0].id]
    assert db.leetcode_on(conn, day(1).astimezone().date())[1:4] == ("two-sum", "amd", 0)
    conn.close()

    pipeline.run(config, now=day(3))
    assert assignments(config)[-1][:2] == (NEETCODE[1].id, "neetcode-150")


def test_a_configured_rotation_is_followed(config, fake_web, model, fake_articles):
    config.leetcode.rotation = ["vanguard", "amd"]

    practise(config, 3)

    assert [(problem, track) for problem, track, _, _, _ in assignments(config)] == [
        (VANGUARD[0].id, "vanguard"), (AMD[0].id, "amd"), (VANGUARD[1].id, "vanguard"),
    ]  # fmt: skip


def test_a_track_that_has_run_out_shows_a_review_marked_as_one(config, fake_web, model, fake_articles):
    config.leetcode.rotation = ["amd"]
    practise(config, len(AMD))

    digest, _ = pipeline.run(config, now=day(len(AMD)))

    rows = assignments(config)
    assert [review for _, _, review, _, _ in rows] == [0] * 17 + [1]
    assert rows[-1][0] == AMD[0].id and len(rows) == 18  # the first problem again; nothing was deleted to allow it
    assert read_latest(config)["leetcode"]["review"] is True
    assert "_Review · Easy · Source: NeetCode 150, AMD (Interview Solver tag)_" in digest


# --- the hint the model words


def test_the_hint_request_is_bounded_and_carries_no_reference_answer(config, fake_web, model, fake_articles):
    pipeline.run(config, now=NOW)

    ((system, prompt, temperature),) = model.hint_requests
    assert temperature == 0.0 and len(system) + len(prompt) < 2000
    assert FIRST.statement in prompt and f"Approved hint: {FIRST.hints[0]}" in prompt
    assert FIRST.approach not in prompt and FIRST.hints[1] not in prompt  # it cannot leak what it never saw
    assert not any(case in prompt for case in FIRST.edge_cases)


@pytest.mark.parametrize(
    "reply",
    [
        {"hint": "Put every value into a hash set and check membership as you go."},  # names the structure
        {"hint": "Sort the array first and then compare each value with its neighbour."},  # names an approach
        {"hint": "You should be able to finish this one in O(n) time with a single pass."},  # states a complexity
        {"hint": "Try this: ```seen = set()``` and then loop over the numbers once."},  # code
        {"hint": "Hmm."},  # too short to be a hint
        {"hint": "Think. " * 60},  # runs on
        {"hint": ["not", "a", "string"]},
        {"lesson": "The model answered a different question altogether."},
    ],
)
def test_a_hint_that_reveals_the_answer_or_is_malformed_gives_way_to_the_catalogs(config, fake_web, model, fake_articles, reply):
    model.hint_reply = reply

    digest, model_ok = pipeline.run(config, now=NOW)

    exercise = read_latest(config)["leetcode"]
    assert (exercise["hint"], exercise["hint_source"]) == (FIRST.hints[0], "catalog")
    assert f"**Hint:** {FIRST.hints[0]}" in digest and not gives_away(FIRST, exercise["hint"])
    assert model_ok and read_latest(config)["status"] == "ok"  # nothing is missing, so the run is not degraded


def test_the_model_cannot_change_or_replace_the_problem(config, fake_web, model, fake_articles):
    model.hint_reply = {
        "hint": MODEL_HINT, "problem_id": "two-sum", "title": "Three Sum", "statement": "Do something else entirely.",
        "difficulty": "hard", "url": "https://example.com/elsewhere", "track": "vanguard",
    }  # fmt: skip

    digest, _ = pipeline.run(config, now=NOW)

    exercise = read_latest(config)["leetcode"]
    assert {key: exercise[key] for key in ("problem_id", "title", "statement", "difficulty", "url", "track")} == {
        "problem_id": FIRST.id, "title": FIRST.title, "statement": FIRST.statement, "difficulty": "easy",
        "url": FIRST.url, "track": "neetcode-150",
    }  # fmt: skip
    assert "Three Sum" not in digest and "example.com/elsewhere" not in digest
    assert assignments(config)[0][0] == FIRST.id


def test_a_hint_is_flattened_to_one_line_of_plain_text(config, fake_web, model, fake_articles):
    model.hint_reply = {"hint": "  What might you want\n\nto remember about [earlier] values?  "}

    digest, _ = pipeline.run(config, now=NOW)

    assert read_latest(config)["leetcode"]["hint"] == "What might you want to remember about [earlier] values?"
    assert "**Hint:** What might you want to remember about \\[earlier\\] values?" in digest  # escaped in Markdown only


def test_model_hints_can_be_switched_off_in_the_config(config, fake_web, model, fake_articles):
    config.leetcode.model_hints = False

    pipeline.run(config, now=NOW)

    assert model.hint_requests == []
    assert assignments(config) == [(FIRST.id, "neetcode-150", 0, FIRST.hints[0], "catalog")]


def test_no_hint_is_requested_once_the_run_budget_is_spent(config, fake_web, model, fake_articles, monkeypatch):
    monkeypatch.setattr(llm, "out_of_time", lambda: True)

    pipeline.run(config, now=NOW)

    assert model.hint_requests == [] and read_latest(config)["leetcode"]["hint_source"] == "catalog"


# --- when the model or the catalog fails


def test_without_ollama_the_exercise_still_appears_with_the_catalogs_hint(config, fake_web, model, fake_articles):
    model.error = llm.LLMError("cannot reach Ollama at http://localhost:11434")

    digest, model_ok = pipeline.run(config, now=NOW)

    document = read_latest(config)
    assert not model_ok and document["status"] == "degraded" and document["lesson"] is None  # news and lesson suffered
    assert document["leetcode"]["problem_id"] == FIRST.id
    assert (document["leetcode"]["hint"], document["leetcode"]["hint_source"]) == (FIRST.hints[0], "catalog")
    assert FIRST.statement in digest and assignments(config) == [(FIRST.id, "neetcode-150", 0, FIRST.hints[0], "catalog")]


def test_only_the_hint_request_failing_leaves_a_complete_digest(config, fake_web, model, fake_articles):
    model.hint_error = llm.LLMError("Ollama did not return valid JSON")

    digest, model_ok = pipeline.run(config, now=NOW)

    assert model_ok and "**What happened:**" in digest and lesson_text(SCHEDULE[0].title) in digest
    assert read_latest(config)["leetcode"]["hint"] == FIRST.hints[0]


def test_a_broken_catalog_costs_only_the_exercise(config, fake_web, model, fake_articles, monkeypatch):
    def broken():
        raise CatalogError("cannot read the LeetCode catalog")

    monkeypatch.setattr(leetcode, "load_catalog", broken)

    digest, model_ok = pipeline.run(config, now=NOW)

    document = read_latest(config)
    assert "**What happened:**" in digest and lesson_text(SCHEDULE[0].title) in digest  # the rest is intact
    assert "_No LeetCode exercise today: it could not be prepared. No problem was used up._" in digest
    assert document["leetcode"] is None and document["lesson"] is not None and len(document["stories"]) == 3
    assert not model_ok and document["status"] == "degraded"  # so a scheduler hears about it
    assert assignments(config) == [] and table_count(config, "lessons") == 1

    monkeypatch.setattr(leetcode, "load_catalog", load_catalog)  # repaired
    pipeline.run(config, now=NOW)
    assert assignments(config)[0][0] == FIRST.id  # the failed day lost nothing: the same first problem


def test_a_run_whose_files_cannot_be_written_does_not_advance_the_rotation(config, fake_web, model, fake_articles, monkeypatch):
    practise(config, 1)
    disk = {"full": True}
    real_fsync = os.fsync

    def fsync(file_descriptor):
        if disk["full"]:
            raise OSError("disk full")
        real_fsync(file_descriptor)

    monkeypatch.setattr(os, "fsync", fsync)
    with pytest.raises(OSError, match="disk full"):
        pipeline.run(config, now=day(1))

    assert [problem for problem, _, _, _, _ in assignments(config)] == [FIRST.id]  # the failed run left no trace
    assert read_latest(config)["leetcode"]["problem_id"] == FIRST.id

    disk["full"] = False
    pipeline.run(config, now=day(1))
    assert assignments(config)[-1][:2] == ("two-sum", "amd")  # AMD's turn was not lost, and not skipped


def test_switched_off_there_is_no_section_no_field_value_and_no_history(config, fake_web, model, fake_articles):
    config.leetcode.enabled = False

    digest, model_ok = pipeline.run(config, now=NOW)

    document = read_latest(config)
    assert model_ok and "LeetCode" not in digest and document["leetcode"] is None and document["status"] == "ok"
    assert model.hint_requests == [] and assignments(config) == []
    assert digest.endswith(f"**{SCHEDULE[0].title}**\n\n{lesson_text(SCHEDULE[0].title)}\n")  # exactly as before


# --- the model's lifecycle, with the real llm module and requests.post faked


CHAT_REPLY = json.dumps({
    "selected": [1, 2, 3], "what_happened": "Something.", "why_it_matters": "Reasons.",
    "lesson": "A lesson that is long enough to pass validation, written by the fake server for tests.",
    "hint": MODEL_HINT,
})  # fmt: skip


class Ollama:
    """Fake Ollama HTTP API that answers every chat request, hints included, and records what was asked."""

    def __init__(self):
        self.requests, self.kinds, self.temperatures = [], [], []

    def post(self, url, json=None, timeout=None):
        endpoint = url.removeprefix("http://localhost:11434/api/")
        self.requests.append((endpoint, json.get("keep_alive")))
        if endpoint != "chat":
            return Response({"done_reason": "unload"})
        self.kinds.append(next(iter(json["format"]["properties"])))
        self.temperatures.append(json["options"]["temperature"])
        return Response({"message": {"content": CHAT_REPLY}})


class Response:
    status_code, text = 200, ""

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload

    def raise_for_status(self):
        pass


def test_the_hint_shares_the_runs_model_load_and_comes_before_the_unload(config, fake_web, fake_articles, monkeypatch):
    ollama = Ollama()
    monkeypatch.setattr(requests, "post", ollama.post)

    pipeline.run(config, now=NOW)

    assert ollama.kinds == ["selected", "what_happened", "what_happened", "what_happened", "lesson", "hint"]
    assert ollama.temperatures[-1] == 0.0
    assert ollama.requests == [("chat", "10m")] * 6 + [("generate", 0)]  # one more request, before the unload

    pipeline.run(config, now=NOW)  # a rerun summarises the three stories left, and reuses the lesson and the exercise

    assert ollama.kinds[6:] == ["what_happened"] * 3 and ollama.requests[-1] == ("generate", 0)


# --- the hint preference


def test_hints_are_on_by_default_and_no_file_is_needed(config):
    assert leetcode.read_hints(config.leetcode_preferences_path) == (True, None)
    assert leetcode.hints_enabled(config) and not config.leetcode_preferences_path.exists()


def test_the_preference_persists_in_the_data_directory(config, tmp_path):
    assert leetcode.set_hints(config, False) is True

    path = config.leetcode_preferences_path
    assert path == tmp_path / "data" / "leetcode_preferences.json"  # beside the database, which Git ignores
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert (stored["version"], stored["hints"]) == (1, False) and stored["updated_at"].endswith("+00:00")
    assert not leetcode.hints_enabled(Config(data_dir=config.data_dir))  # a new process reads the same choice

    assert leetcode.set_hints(config, False) is False  # already off
    assert leetcode.set_hints(config, True) is True and leetcode.hints_enabled(config)
    assert sorted(entry.name for entry in path.parent.iterdir()) == ["leetcode_preferences.json"]  # no stray files


def test_a_damaged_preferences_file_shows_no_hint_and_the_command_repairs_it(config, caplog):
    config.leetcode_preferences_path.parent.mkdir(parents=True)
    config.leetcode_preferences_path.write_text('{"version": 1, "hints": "yes"}', encoding="utf-8")

    enabled, problem = leetcode.read_hints(config.leetcode_preferences_path)
    assert not enabled and "not a valid LeetCode preferences file" in problem
    assert not leetcode.hints_enabled(config) and "showing no hint" in caplog.text

    assert leetcode.set_hints(config, True) is True  # replacing the file counts as a change
    assert leetcode.read_hints(config.leetcode_preferences_path) == (True, None)


def test_with_hints_off_the_digest_shows_none_and_the_model_is_not_asked(config, fake_web, model, fake_articles):
    leetcode.set_hints(config, False)

    digest, model_ok = pipeline.run(config, now=NOW)

    exercise = read_latest(config)["leetcode"]
    assert model_ok and "**Hint:**" not in digest and FIRST.hints[0] not in digest
    assert (exercise["hints_enabled"], exercise["hint"], exercise["hint_source"]) == (False, None, None)
    assert model.hint_requests == [] and assignments(config) == [(FIRST.id, "neetcode-150", 0, None, None)]


def test_changing_the_preference_never_changes_or_advances_the_days_exercise(config, fake_web, model, fake_articles):
    leetcode.set_hints(config, False)
    pipeline.run(config, now=NOW)

    leetcode.set_hints(config, True)  # the change alone runs nothing
    assert assignments(config) == [(FIRST.id, "neetcode-150", 0, None, None)] and table_count(config, "runs") == 1

    digest, _ = pipeline.run(config, now=NOW)  # the day's exercise, now with the hint written for it
    assert f"**Hint:** {MODEL_HINT}" in digest
    assert assignments(config) == [(FIRST.id, "neetcode-150", 0, MODEL_HINT, "model")]

    leetcode.set_hints(config, False)
    digest, _ = pipeline.run(config, now=NOW)  # hidden again at once, and kept for later
    assert "**Hint:**" not in digest and read_latest(config)["leetcode"]["hint"] is None
    assert assignments(config) == [(FIRST.id, "neetcode-150", 0, MODEL_HINT, "model")]

    leetcode.set_hints(config, True)
    pipeline.run(config, now=NOW)
    assert read_latest(config)["leetcode"]["hint"] == MODEL_HINT and len(model.hint_requests) == 1
    assert read_latest(config)["leetcode"]["problem_id"] == FIRST.id


# --- rendering


def test_the_section_shows_the_problem_and_the_questions_but_not_the_answer():
    two_sum = CATALOG.get("two-sum")
    exercise = exercise_of(two_sum, "amd", hint="Could remembering earlier elements help?", hint_source="model")

    digest = render.render_digest(date(2026, 10, 9), [], [], None, exercise)

    assert digest.endswith(
        "## LeetCode Micro-Lesson\n"
        "\n"
        "**[Two Sum](https://leetcode.com/problems/two-sum/)**\n"
        "\n"
        "_Easy · Source: NeetCode 150, AMD (Interview Solver tag)_\n"
        "\n"
        "Given an integer array and a target, return the indices of the two different elements that add up to the target.\n"
        "\n"
        "**Example:**\n"
        "\n"
        "- Input: `nums = [2, 7, 11, 15], target = 9`\n"
        "- Output: `[0, 1]`\n"
        "\n"
        "**Constraints:** 2 ≤ n ≤ 10^4; exactly one valid pair exists\n"
        "\n"
        "**Think about:**\n"
        "\n"
        "1. What data structure would you choose?\n"
        "2. How would your algorithm work at a high level?\n"
        "3. What would its time complexity be?\n"
        "4. What would its space complexity be?\n"
        "5. What edge cases should you consider?\n"
        "\n"
        "**Hint:** Could remembering earlier elements help?\n"
        "\n"
        "_No implementation required: describe your approach in words._\n"
    )
    assert "hash" not in digest.lower() and "O(n)" not in digest


def test_review_and_premium_are_noted_and_a_hint_is_shown_only_while_hints_are_on():
    rooms = CATALOG.get("meeting-rooms")
    shown = render.render_digest(date(2026, 10, 9), [], [], None, exercise_of(rooms, review=True, hint="A hint."))
    hidden = render.render_digest(date(2026, 10, 9), [], [], None, exercise_of(rooms, hint="A hint.", hints_on=False))

    assert "_Review · Easy · Source: NeetCode 150 · LeetCode Premium_" in shown and "**Hint:** A hint." in shown
    assert "_Easy · Source: NeetCode 150 · LeetCode Premium_" in hidden and "Hint" not in hidden


def test_every_problem_renders_and_serialises():
    for problem in CATALOG.problems:
        exercise = exercise_of(problem, hint=problem.hints[0], hint_source="catalog")
        digest = render.render_digest(date(2026, 10, 9), [], [], None, exercise)
        document = output.leetcode_document(exercise)

        assert f"]({problem.url})**" in digest and "### " not in digest.split("## LeetCode Micro-Lesson")[1]
        assert list(document) == DOCUMENT_KEYS and json.loads(json.dumps(document)) == document
        assert document["company_tags"] == [CATALOG.sources[t].name for t in problem.tracks if t != "neetcode-150"]
        assert problem.approach not in digest  # the Markdown never holds the answer


def test_every_catalog_problem_has_a_complete_reference_answer_taken_from_the_catalog_as_written():
    for problem in CATALOG.problems:
        assert output.reference_solution(problem) == {
            "source": "catalog",
            "complete": True,
            "topic": CATEGORIES[problem.category],
            "approach": problem.approach,
            "time": problem.time,
            "space": problem.space,
            "edge_cases": list(problem.edge_cases),
        }


@pytest.mark.parametrize(
    "missing, nulls",
    [
        ({"edge_cases": ()}, ["edge_cases"]),
        ({"time": "", "space": " "}, ["time", "space"]),
        ({"approach": ""}, ["approach"]),
        ({"approach": "", "time": "", "space": ""}, ["approach", "time", "space"]),
    ],
)  # fmt: skip
def test_a_reference_answer_with_parts_missing_is_partial_and_nothing_is_filled_in(missing, nulls):
    problem = replace(FIRST, **missing)

    reference = output.reference_solution(problem)

    assert list(reference) == REFERENCE_KEYS and reference["complete"] is False
    assert [key for key in REFERENCE_KEYS if reference[key] is None] == nulls  # null, never an empty string or list
    kept = {key: reference[key] for key in ("approach", "time", "space") if key not in nulls}
    assert kept == {key: getattr(FIRST, key) for key in kept}


def test_a_problem_the_catalog_has_no_answer_for_gets_null_and_the_exercise_is_otherwise_whole():
    bare = replace(FIRST, approach="", time="", space="", edge_cases=())
    exercise = exercise_of(bare, hint="A hint.", hint_source="catalog")

    document = output.leetcode_document(exercise)

    assert output.reference_solution(bare) is None  # the topic alone is not an answer
    assert list(document) == DOCUMENT_KEYS and document["reference_solution"] is None
    assert (document["statement"], document["hint"]) == (FIRST.statement, "A hint.")
    assert "## LeetCode Micro-Lesson" in render.render_digest(date(2026, 10, 9), [], [], None, exercise)


def test_the_reference_answer_can_be_left_out_of_output_meant_for_a_person():
    exercise = exercise_of(FIRST, hint="A hint.", hint_source="catalog")

    assert list(output.leetcode_document(exercise, with_reference=False)) == PUBLIC_KEYS


def test_without_an_exercise_the_digest_is_unchanged_and_the_field_is_null():
    before = render.render_digest(date(2026, 10, 9), [], [], None)

    assert render.render_digest(date(2026, 10, 9), [], [], None, None, False) == before and "LeetCode" not in before
    assert render.render_digest(date(2026, 10, 9), [], [], None, None, True).startswith(before)
    assert output.leetcode_document(None) is None


# --- existing consumers


def test_every_earlier_key_keeps_its_place_and_meaning(config, fake_web, model, fake_articles):
    pipeline.run(config, now=NOW)

    document = read_latest(config)
    assert list(document) == [*EARLIER_KEYS, "leetcode"]  # one key added at the end; schema version unchanged
    assert document["schema_version"] == output.SCHEMA_VERSION == 1
    assert len(document["stories"]) == 3 and document["lesson"]["topic_id"] == SCHEDULE[0].id
    assert document["lesson"]["lesson"] == lesson_text(SCHEDULE[0].title) and document["recall"] is None


def test_the_news_and_the_lesson_are_the_same_with_and_without_the_exercise(config, fake_web, model, fake_articles, tmp_path):
    without = Config(data_dir=str(tmp_path / "other"))
    without.rss.feeds, without.final_story_count, without.leetcode.enabled = [FEED], 3, False

    with_exercise, _ = pipeline.run(config, now=NOW)
    plain, _ = pipeline.run(without, now=NOW)

    assert with_exercise.startswith(plain) and with_exercise[len(plain) :].startswith("\n## LeetCode Micro-Lesson\n")
    a, b = read_latest(config), read_latest(without)
    assert {key: a[key] for key in EARLIER_KEYS} == {key: b[key] for key in EARLIER_KEYS}


def test_archives_history_and_the_markdown_check_work_with_the_new_section(config, fake_web, model, fake_articles):
    digest, _ = pipeline.run(config, now=NOW)
    document = read_latest(config)

    assert render.describes(digest, document)  # the section does not look like a sixth story
    (run,) = history.archived_runs(config)
    assert (run["run_id"], run["story_count"], run["has_lesson"], run["status"]) == (1, 3, True, "ok")
    assert json.loads(open(run["json"], encoding="utf-8").read())["leetcode"]["problem_id"] == FIRST.id
    assert open(run["markdown"], encoding="utf-8").read() == digest
    assert history.backfill(config)[0]["outcome"] == "already_archived"


def test_a_database_from_before_the_exercise_gains_the_tables_and_keeps_its_history(config, fake_web, model, fake_articles):
    config.leetcode.enabled = False
    pipeline.run(config, now=day(0))
    conn = sqlite3.connect(config.db_path)
    for table in ("leetcode_assignments", "leetcode_turns", "leetcode_progress"):
        conn.execute(f"DROP TABLE {table}")  # the database as an earlier version left it
    conn.commit()
    conn.close()

    config.leetcode.enabled = True
    pipeline.run(config, now=day(1))

    assert table_count(config, "runs") == 2 and table_count(config, "lessons") == 2  # nothing earlier was lost
    assert assignments(config) == [(FIRST.id, "neetcode-150", 0, MODEL_HINT, "model")]


# --- configuration and the CLI


def test_the_default_configuration_is_on_with_the_three_track_rotation():
    settings = Config().leetcode

    assert settings.enabled and settings.model_hints and settings.rotation == ["neetcode-150", "amd", "vanguard"]
    assert (settings.feedback_budget_seconds, settings.keep_alive_seconds) == (120, 300)


def test_the_config_file_can_change_the_rotation_and_switch_the_exercise_off(tmp_path):
    path = tmp_path / "dailygrad.toml"
    path.write_text('[leetcode]\nenabled = false\nrotation = ["amd", "neetcode-150"]\nmodel_hints = false\nkeep_alive_seconds = 0\n')

    settings = load_config(path).leetcode

    assert not settings.enabled and not settings.model_hints and settings.keep_alive_seconds == 0
    assert settings.rotation == ["amd", "neetcode-150"]


@pytest.mark.parametrize(
    "text, message",
    [
        ('[leetcode]\nrotation = ["google"]', "leetcode.rotation must list one or more of: neetcode-150, amd, vanguard"),
        ("[leetcode]\nrotation = []", "leetcode.rotation must list one or more of"),
        ('[leetcode]\nrotation = "amd"', "leetcode.rotation must be of type list"),
        ("[leetcode]\nfeedback_budget_seconds = 0", "leetcode.feedback_budget_seconds must be at least 1"),
        ("[leetcode]\nkeep_alive_seconds = -1", "leetcode.keep_alive_seconds 0 or more"),
        ("[leetcode]\ndaily = true", "unknown setting: leetcode.daily"),
    ],
)
def test_invalid_leetcode_settings_are_configuration_errors(tmp_path, capsys, text, message):
    path = tmp_path / "dailygrad.toml"
    path.write_text(text)

    with pytest.raises(ConfigError, match=message):
        load_config(path)
    assert cli.main(["run", "--config", str(path)]) == 2 and message in capsys.readouterr().err


def test_dailygrad_config_reports_the_exercise_and_the_preferences_file(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DAILYGRAD_CONFIG", raising=False)

    assert cli.main(["config"]) == 0

    shown = capsys.readouterr().out
    assert (
        "LeetCode:           one exercise at a time, kept until completed or skipped, "
        "rotating neetcode-150 -> amd -> vanguard; hints on"
    ) in shown
    assert f"LeetCode settings:  {(tmp_path / 'data' / 'leetcode_preferences.json').resolve()}" in shown
    assert f"Latest JSON:        {(tmp_path / 'data' / 'latest.json').resolve()}" in shown  # the earlier rows are unchanged
    assert not (tmp_path / "data").exists()


def test_the_packaged_catalog_is_what_an_installed_copy_reads():
    from importlib import resources

    assert (resources.files("dailygrad") / "leetcode.toml").is_file()
    pyproject = (Path(__file__).parent.parent / "pyproject.toml").read_text(encoding="utf-8")
    assert '"leetcode.toml"' in pyproject  # declared as package data, so a wheel carries it
