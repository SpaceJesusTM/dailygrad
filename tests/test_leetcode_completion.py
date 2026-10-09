"""The LeetCode exercise is kept until the user ends it: carry-over days, completing, moving on, and old databases."""

import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest

from dailygrad import cli, db, history, leetcode, pipeline, render, tutor
from test_leetcode import AMD, CATALOG, FIRST, MODEL_HINT, NEETCODE, VANGUARD, assignments, config, exercise_of, model, practise  # noqa: F401 (fixtures)
from test_pipeline import day, fake_articles, fake_web, read_latest, table_count  # noqa: F401 (fixtures)

TWO_SUM = AMD[0]  # the second exercise of the default rotation


def local(number):
    """The date of day(number), as a digest names it."""
    return day(number).astimezone().date().isoformat()


def shown(config):
    """The exercise in the newest digest's JSON."""
    return read_latest(config)["leetcode"]


def rows(config, table):
    conn = sqlite3.connect(config.db_path)
    result = conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
    conn.close()
    return result


def files(config):
    """Every file DailyGrad wrote but its database, with its contents."""
    root = Path(config.data_dir)
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file() and p.suffix != ".db"}


def refused(call):
    with pytest.raises(tutor.TutorError) as error:
        call()
    return error.value.code


@pytest.fixture
def config_file(tmp_path, config):
    path = tmp_path / "dailygrad.toml"
    path.write_text(f'data_dir = "{Path(config.data_dir).as_posix()}"\n')
    return str(path)


def run_cli(capsys, arguments):
    code = cli.main(["leetcode", *arguments])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


# --- an exercise is kept until it is completed


def test_an_exercise_is_shown_again_each_day_until_it_is_completed(config, fake_web, model, fake_articles):
    pipeline.run(config, now=day(0))
    first = shown(config)
    assert (first["problem_id"], first["day"], first["is_carryover"], first["awaiting_completion"]) == (FIRST.id, 1, False, True)

    for number in range(1, 5):
        digest, model_ok = pipeline.run(config, now=day(number))
        again = shown(config)

        assert model_ok and f"**[{FIRST.title}]({FIRST.url})**" in digest and FIRST.statement in digest
        assert (again["day"], again["is_carryover"], again["assigned_on"]) == (number + 1, True, local(0))
        # Everything else is what the first day showed: the track, the sources, the problem, the hint, the answer.
        placed = {"day": first["day"], "is_carryover": False}
        assert again | placed == first

    assert assignments(config) == [(FIRST.id, "neetcode-150", 0, MODEL_HINT, "model")]  # one exercise, five days
    assert table_count(config, "runs") == 5 and table_count(config, "leetcode_showings") == 5
    assert len(model.hint_requests) == 1  # carrying an exercise over asks the model for nothing


def test_a_carried_over_exercise_is_labelled_and_is_not_a_review(config, fake_web, model, fake_articles):
    first, _ = pipeline.run(config, now=day(0))
    third = [pipeline.run(config, now=day(number))[0] for number in (1, 2)][-1]

    assigned = date.fromisoformat(local(0))
    label = f"**Still in progress — originally assigned {assigned:%B} {assigned.day}** (day 3).\n"
    assert label in third and "Still in progress" not in first
    assert "_Easy · Source: NeetCode 150_" in third and "Review" not in third
    assert shown(config)["review"] is False
    assert FIRST.approach not in third and "reference" not in third.lower()  # the answer stays out of the Markdown


def test_completing_moves_the_next_digest_to_the_next_track_and_not_before(config, fake_web, model, fake_articles):
    for number in range(4):
        pipeline.run(config, now=day(number))
    before = files(config)

    result = tutor.complete(config, now=day(3))

    assert result == {
        "ok": True,
        "action": "complete",
        "changed": True,
        "exercise": {
            "exercise_id": 1, "problem_id": FIRST.id, "number": FIRST.number, "title": FIRST.title, "url": FIRST.url,
            "track": "neetcode-150", "review": False, "assigned_on": local(0), "days_shown": 4,
            "outcome": "completed", "closed_at": day(3).isoformat(),
        },
        "completion_pending": False,
        "next_track": {"id": "amd", "name": "AMD"},
    }  # fmt: skip
    # Completing chooses nothing and writes nothing but its own row: no digest, no run, no model request.
    assert files(config) == before and table_count(config, "runs") == 4 and len(assignments(config)) == 1
    assert len(model.hint_requests) == 1

    pipeline.run(config, now=day(4))
    after = shown(config)
    assert (after["problem_id"], after["track"], after["exercise_id"]) == (TWO_SUM.id, "amd", 2)
    assert (after["day"], after["is_carryover"], after["assigned_on"], after["awaiting_completion"]) == (1, False, local(4), True)


def test_each_exercise_takes_one_turn_of_the_rotation_however_many_days_it_lasts(config, fake_web, model, fake_articles):
    for number in range(4):  # NeetCode, for four days
        pipeline.run(config, now=day(number))
    tutor.complete(config, now=day(3))
    for number in (4, 5):  # AMD, for two
        pipeline.run(config, now=day(number))
    tutor.complete(config, now=day(5))
    pipeline.run(config, now=day(6))  # Vanguard
    tutor.complete(config, now=day(6))
    pipeline.run(config, now=day(7))  # and round again

    assert [(problem, track) for problem, track, _, _, _ in assignments(config)] == [
        (NEETCODE[0].id, "neetcode-150"), (AMD[0].id, "amd"), (VANGUARD[0].id, "vanguard"), (NEETCODE[1].id, "neetcode-150"),
    ]  # fmt: skip
    progress = tutor.status(config, now=day(7))["progress"]
    assert (progress["exercises"], progress["completed"], progress["skipped"]) == (4, 3, 0)


def test_a_rerun_keeps_the_days_exercise_even_after_it_was_completed(config, fake_web, model, fake_articles):
    pipeline.run(config, now=day(0))
    pipeline.run(config, now=day(1))
    morning = shown(config)
    tutor.complete(config, now=day(1))

    digest, _ = pipeline.run(config, now=day(1))  # the same day, after completing

    again = shown(config)
    assert again | {"awaiting_completion": True} == morning and again["awaiting_completion"] is False
    assert "_Already completed: the next digest brings a new exercise._" in digest and "Still in progress" not in digest
    assert len(assignments(config)) == 1  # the rerun did not start the next exercise early

    pipeline.run(config, now=day(2))
    assert shown(config)["problem_id"] == TWO_SUM.id and len(assignments(config)) == 2


def test_completing_twice_changes_nothing_the_second_time_and_skips_nothing(config, fake_web, model, fake_articles):
    pipeline.run(config, now=day(0))

    first = tutor.complete(config, exercise_id=1, now=day(0))
    second = tutor.complete(config, exercise_id=1, now=day(1))
    third = tutor.complete(config, now=day(1))

    assert (first["changed"], second["changed"], third["changed"]) == (True, False, False)
    assert second["exercise"] == first["exercise"]  # still closed at the first time
    assert rows(config, "leetcode_outcomes") == [(1, "completed", day(0).isoformat())]

    pipeline.run(config, now=day(1))
    assert [problem for problem, *_ in assignments(config)] == [FIRST.id, TWO_SUM.id]  # one step, not three

    late = tutor.complete(config, exercise_id=1, now=day(1))  # a retry that arrives after the next was assigned
    assert late["changed"] is False and late["completion_pending"] is True and late["next_track"] is None
    assert tutor.status(config, now=day(1))["active_exercise_id"] == 2  # the new exercise is untouched


def test_nothing_but_the_users_word_completes_an_exercise(config, fake_web, model, fake_articles):
    pipeline.run(config, now=day(0))

    tutor.next_hint(config, now=day(0))
    for state in ("attempted", "needs-review", "comfortable", "solved"):
        tutor.mark(config, state, now=day(0))
    tutor.set_hints(config, False)

    status = tutor.status(config, now=day(0))
    assert status["completion_pending"] and status["current"]["outcome"] is None
    assert (status["progress"]["solved_in_code"], status["progress"]["completed"]) == (1, 0)
    pipeline.run(config, now=day(1))
    assert shown(config)["problem_id"] == FIRST.id and rows(config, "leetcode_outcomes") == []


def test_completed_and_solved_in_code_are_kept_apart(config, fake_web, model, fake_articles):
    pipeline.run(config, now=day(0))

    tutor.complete(config, now=day(0))

    state = tutor.status(config, now=day(0))
    assert (state["progress"]["completed"], state["progress"]["solved_in_code"], state["progress"]["attempted"]) == (1, 0, 0)
    assert state["current"]["state"] == {"times_shown": 1, "attempted": False, "confidence": None, "solved_in_code": False}
    assert rows(config, "leetcode_progress") == []  # completing says nothing about the problem

    tutor.mark(config, "solved", now=day(0))
    tutor.mark(config, "clear", now=day(0))  # and withdrawing the solve does not reopen the exercise
    assert tutor.status(config, now=day(0))["current"]["outcome"] == "completed"


def test_a_completion_aimed_at_another_exercise_is_refused_and_changes_nothing(config, fake_web, model, fake_articles):
    practise(config, 1)
    pipeline.run(config, now=day(1))  # two-sum is the current exercise; contains-duplicate is history

    assert refused(lambda: tutor.complete(config, problem_id=FIRST.id, now=day(1))) == "stale_exercise"
    assert refused(lambda: tutor.complete(config, exercise_id=2, problem_id=FIRST.id, now=day(1))) == "stale_exercise"
    assert refused(lambda: tutor.complete(config, exercise_id=7, now=day(1))) == "unknown_exercise"
    for malformed in ("0", "-1", "1; DROP TABLE runs", "two-sum", "1234567890", ""):
        assert refused(lambda: tutor.complete(config, exercise_id=malformed, now=day(1))) == "unknown_exercise"
    assert refused(lambda: tutor.complete(config, problem_id="not-a-problem", now=day(1))) == "unknown_problem"
    assert refused(lambda: tutor.complete(config, problem_id="../etc/passwd", now=day(1))) == "unknown_problem"

    assert rows(config, "leetcode_outcomes") == [(1, "completed", day(0).isoformat())]
    assert tutor.status(config, now=day(1))["active_exercise_id"] == 2
    # Named correctly, by either identity or both, it is completed.
    assert tutor.complete(config, exercise_id=2, problem_id=TWO_SUM.id, now=day(1))["changed"] is True


def test_a_review_of_a_problem_completed_before_waits_for_its_own_completion(config, fake_web, model, fake_articles):
    config.leetcode.rotation = ["amd"]
    practise(config, len(AMD))

    pipeline.run(config, now=day(17))  # the track has run out: its first problem again, as a review
    tutor.mark(config, "solved", now=day(17))  # the user has even solved that problem in code
    for number in (18, 19):
        digest, _ = pipeline.run(config, now=day(number))
    review = shown(config)

    assert (review["problem_id"], review["review"], review["exercise_id"]) == (AMD[0].id, True, 18)
    assert (review["day"], review["is_carryover"], review["awaiting_completion"]) == (3, True, True)
    assert "_Review · Easy · Source: NeetCode 150, AMD (Interview Solver tag)_" in digest and "(day 3)" in digest
    assert len(assignments(config)) == 18  # its earlier completion and its solve finished nothing here

    tutor.complete(config, exercise_id=18, now=day(19))
    pipeline.run(config, now=day(20))
    assert shown(config)["exercise_id"] == 19 and shown(config)["review"] is True
    assert tutor.status(config, now=day(20))["progress"]["completed"] == 18


def test_the_hint_stays_the_same_and_the_preference_still_applies_while_an_exercise_is_pending(config, fake_web, model, fake_articles):
    pipeline.run(config, now=day(0))
    model.hint_reply = {"hint": "A different wording that a later day must not adopt, however good it is."}

    leetcode.set_hints(config, False)
    digest, _ = pipeline.run(config, now=day(1))
    assert "**Hint:**" not in digest and (shown(config)["hints_enabled"], shown(config)["hint"]) == (False, None)

    leetcode.set_hints(config, True)
    digest, _ = pipeline.run(config, now=day(2))
    assert f"**Hint:** {MODEL_HINT}" in digest and shown(config)["hint"] == MODEL_HINT
    assert len(model.hint_requests) == 1 and shown(config)["problem_id"] == FIRST.id


def test_an_exercise_first_shown_with_hints_off_gets_its_hint_once_when_they_are_turned_on(config, fake_web, model, fake_articles):
    leetcode.set_hints(config, False)
    pipeline.run(config, now=day(0))
    leetcode.set_hints(config, True)

    for number in (1, 2, 3):
        pipeline.run(config, now=day(number))

    assert shown(config)["hint"] == MODEL_HINT and len(model.hint_requests) == 1
    assert assignments(config) == [(FIRST.id, "neetcode-150", 0, MODEL_HINT, "model")]


def test_every_archived_digest_keeps_what_it_showed(config, fake_web, model, fake_articles):
    pipeline.run(config, now=day(0))
    pipeline.run(config, now=day(1))
    archived = {run["run_id"]: Path(run["json"]).read_bytes() for run in history.archived_runs(config)}

    tutor.complete(config, now=day(1))
    pipeline.run(config, now=day(2))
    tutor.advance(config, now=day(2))
    pipeline.run(config, now=day(3))

    runs = {run["run_id"]: Path(run["json"]) for run in history.archived_runs(config)}
    assert len(runs) == 4 and all(runs[run_id].read_bytes() == content for run_id, content in archived.items())
    told = [json.loads(runs[run_id].read_text(encoding="utf-8"))["leetcode"] for run_id in sorted(runs)]
    assert [(e["problem_id"], e["day"], e["is_carryover"]) for e in told] == [
        (FIRST.id, 1, False), (FIRST.id, 2, True), (TWO_SUM.id, 1, False), (VANGUARD[0].id, 1, False),
    ]  # fmt: skip


# --- moving on


def test_moving_on_skips_the_exercise_and_assigns_the_next_at_once(config, fake_web, model, fake_articles):
    pipeline.run(config, now=day(0))
    before = files(config)

    result = tutor.advance(config, now=day(0))  # no attempt, no answer, no reason

    assert result["ok"] and (result["action"], result["changed"]) == ("next", True)
    assert result["previous"] == {
        "exercise_id": 1, "problem_id": FIRST.id, "number": FIRST.number, "title": FIRST.title, "url": FIRST.url,
        "track": "neetcode-150", "review": False, "assigned_on": local(0), "days_shown": 1,
        "outcome": "skipped", "closed_at": day(0).isoformat(),
    }  # fmt: skip
    active = result["active"]
    assert (active["exercise_id"], active["problem_id"], active["track"]) == (2, TWO_SUM.id, "amd")
    assert (active["statement"], active["example"]["output"], active["constraints"]) == (
        TWO_SUM.statement, TWO_SUM.example_output, list(TWO_SUM.constraints),
    )  # fmt: skip
    assert (active["assigned_on"], active["day"], active["is_carryover"], active["awaiting_completion"]) == (None, 0, False, True)
    # Safe to read out: no answer, no topic, and no hint until a digest words one.
    told = json.dumps(result)
    assert "reference_solution" not in active and active["hint"] is None
    for hidden in (TWO_SUM.approach, *TWO_SUM.hints, *TWO_SUM.edge_cases, "Arrays & Hashing"):
        assert hidden not in told
    # Nothing was generated: no run, no digest, no model request.
    assert files(config) == before and table_count(config, "runs") == 1 and len(model.hint_requests) == 1
    assert rows(config, "leetcode_assignments")[1][:5] == (2, 0, TWO_SUM.id, "amd", 0)  # run 0: not in a digest yet


def test_a_skipped_exercise_counts_as_neither_completed_attempted_nor_solved(config, fake_web, model, fake_articles):
    pipeline.run(config, now=day(0))

    tutor.advance(config, now=day(0))

    status = tutor.status(config, now=day(0))
    assert status["progress"] | {"problems": 0} == {
        "problems": 0, "shown": 2, "exercises": 2, "completed": 0, "skipped": 1,
        "attempted": 0, "needs_review": 0, "comfortable": 0, "solved_in_code": 0,
    }  # fmt: skip
    assert rows(config, "leetcode_progress") == [] and rows(config, "leetcode_outcomes") == [(1, "skipped", day(0).isoformat())]
    assert (status["active_exercise_id"], status["completion_pending"]) == (2, True)
    assert (status["current"]["problem_id"], status["current"]["date"], status["current"]["is_today"]) == (TWO_SUM.id, None, False)
    # Assigned between digests, it has been shown on no day yet: it is not a carry-over, whatever day it is.
    assert (status["current"]["day"], status["current"]["is_carryover"], status["current"]["assigned_on"]) == (0, False, None)
    later = tutor.status(config, now=day(3))["current"]  # still so days later, if no digest has run
    assert (later["day"], later["is_carryover"], later["is_today"]) == (0, False, False)
    assert status["next_track"]["id"] == "vanguard"


def test_the_next_digest_shows_the_exercise_that_moving_on_assigned(config, fake_web, model, fake_articles):
    pipeline.run(config, now=day(0))
    tutor.advance(config, now=day(0))

    digest, model_ok = pipeline.run(config, now=day(1))

    today = shown(config)
    assert model_ok and f"**[{TWO_SUM.title}]({TWO_SUM.url})**" in digest and "Still in progress" not in digest
    assert (today["exercise_id"], today["problem_id"], today["day"], today["is_carryover"], today["assigned_on"]) == (
        2, TWO_SUM.id, 1, False, local(1),
    )  # fmt: skip
    assert today["hint"] == MODEL_HINT and len(model.hint_requests) == 2  # its hint is worded by its first digest
    assert len(assignments(config)) == 2 and rows(config, "leetcode_assignments")[1][1] == 2  # now named by that run

    pipeline.run(config, now=day(2))
    assert (shown(config)["problem_id"], shown(config)["day"], shown(config)["is_carryover"]) == (TWO_SUM.id, 2, True)


def test_a_rerun_on_the_day_of_moving_on_still_shows_that_days_exercise(config, fake_web, model, fake_articles):
    pipeline.run(config, now=day(0))
    morning = files(config)
    tutor.advance(config, now=day(0))
    assert files(config) == morning  # the digest already written is untouched

    digest, _ = pipeline.run(config, now=day(0))

    assert (shown(config)["problem_id"], shown(config)["awaiting_completion"]) == (FIRST.id, False)
    assert "_Already skipped: the next digest brings a new exercise._" in digest
    assert len(assignments(config)) == 2 and tutor.status(config, now=day(0))["active_exercise_id"] == 2


def test_each_request_to_move_on_advances_exactly_one_exercise(config, fake_web, model, fake_articles):
    pipeline.run(config, now=day(0))

    first = tutor.advance(config, exercise_id=1, now=day(0))
    retry = tutor.advance(config, exercise_id=1, now=day(0))  # the same tool call, sent again

    assert (first["changed"], retry["changed"]) == (True, False)
    assert retry["active"] == first["active"] and retry["previous"] == first["previous"]
    assert [problem for problem, *_ in assignments(config)] == [FIRST.id, TWO_SUM.id]

    second = tutor.advance(config, exercise_id=2, now=day(0))  # a new request, about the new exercise
    assert (second["changed"], second["previous"]["outcome"], second["active"]["problem_id"]) == (True, "skipped", VANGUARD[0].id)
    assert [track for _, track, *_ in assignments(config)] == ["neetcode-150", "amd", "vanguard"]

    # By now exercise 1 is two behind: a request still naming it is stale, not a retry.
    assert refused(lambda: tutor.advance(config, exercise_id=1, now=day(0))) == "stale_exercise"
    assert refused(lambda: tutor.complete(config, exercise_id=1, now=day(0))) == "stale_exercise"  # skipped, not completed
    assert refused(lambda: tutor.advance(config, problem_id=FIRST.id, now=day(0))) == "stale_exercise"
    assert refused(lambda: tutor.advance(config, exercise_id=9, now=day(0))) == "unknown_exercise"
    assert len(assignments(config)) == 3 and tutor.status(config, now=day(0))["active_exercise_id"] == 3


def test_moving_on_after_completing_assigns_the_next_without_skipping_anything(config, fake_web, model, fake_articles):
    pipeline.run(config, now=day(0))
    tutor.complete(config, now=day(0))

    result = tutor.advance(config, exercise_id=1, now=day(0))

    assert (result["changed"], result["previous"]["outcome"], result["active"]["problem_id"]) == (True, "completed", TWO_SUM.id)
    progress = tutor.status(config, now=day(0))["progress"]
    assert (progress["completed"], progress["skipped"], progress["exercises"]) == (1, 0, 2)
    assert tutor.advance(config, exercise_id=1, now=day(0))["changed"] is False  # and a retry does no more

    pipeline.run(config, now=day(1))
    assert shown(config)["problem_id"] == TWO_SUM.id and len(assignments(config)) == 2


def test_moving_on_after_working_on_an_exercise_keeps_what_was_said_about_it(config, fake_web, model, fake_articles):
    pipeline.run(config, now=day(0))
    tutor.next_hint(config, now=day(0))
    tutor.mark(config, "attempted", now=day(0))
    tutor.mark(config, "needs-review", now=day(0))

    tutor.advance(config, now=day(0))

    progress = tutor.status(config, now=day(0))["progress"]
    assert (progress["attempted"], progress["needs_review"], progress["skipped"], progress["completed"]) == (1, 1, 1, 0)
    assert len(rows(config, "leetcode_turns")) == 1
    # Follow-ups are now about the new exercise, and its hints start from the beginning.
    hint = tutor.next_hint(config, now=day(0))
    assert (hint["problem"]["id"], hint["hint_number"], hint["hint"]) == (TWO_SUM.id, 1, TWO_SUM.hints[0])


def test_completing_and_moving_on_are_recorded_as_different_outcomes(config, fake_web, model, fake_articles):
    pipeline.run(config, now=day(0))
    tutor.complete(config, now=day(0))
    pipeline.run(config, now=day(1))
    tutor.advance(config, now=day(1))
    pipeline.run(config, now=day(2))

    assert [(assignment, outcome) for assignment, outcome, _ in rows(config, "leetcode_outcomes")] == [(1, "completed"), (2, "skipped")]
    assert [track for _, track, *_ in assignments(config)] == ["neetcode-150", "amd", "vanguard"]  # one turn each
    assert shown(config)["problem_id"] == VANGUARD[0].id


def test_moving_on_is_refused_while_exercises_are_switched_off_or_before_the_first(config, fake_web, model, fake_articles):
    assert refused(lambda: tutor.advance(config, now=day(0))) == "no_exercise"
    assert refused(lambda: tutor.complete(config, now=day(0))) == "no_exercise"
    assert not Path(config.data_dir).exists()  # and nothing was created to find that out

    pipeline.run(config, now=day(0))
    config.leetcode.enabled = False
    assert refused(lambda: tutor.advance(config, now=day(0))) == "leetcode_disabled"
    assert len(assignments(config)) == 1 and rows(config, "leetcode_outcomes") == []


# --- failures and overlaps


def test_moving_on_happens_whole_or_not_at_all(config, fake_web, model, fake_articles, monkeypatch):
    pipeline.run(config, now=day(0))

    def broken(*args):
        raise RuntimeError("the catalog went away")

    monkeypatch.setattr(leetcode, "assign", broken)
    with pytest.raises(RuntimeError):
        tutor.advance(config, now=day(0))

    assert rows(config, "leetcode_outcomes") == [] and len(assignments(config)) == 1  # not skipped without a successor
    assert tutor.status(config, now=day(0))["active_exercise_id"] == 1


def test_moving_on_during_a_run_that_is_choosing_the_next_exercise_spends_one_turn(config, fake_web, model, fake_articles, monkeypatch):
    practise(config, 1)
    real = leetcode.write_hint

    def meanwhile(problem, settings):  # the user asks for the next question while the run is at work
        told = tutor.advance(config, exercise_id=1, now=day(1))
        assert told["active"]["problem_id"] == problem.id  # the same choice, made from the same history
        return real(problem, settings)

    monkeypatch.setattr(leetcode, "write_hint", meanwhile)
    pipeline.run(config, now=day(1))

    assert [problem for problem, *_ in assignments(config)] == [FIRST.id, TWO_SUM.id]  # not assigned twice
    assert (shown(config)["exercise_id"], shown(config)["problem_id"], shown(config)["hint"]) == (2, TWO_SUM.id, MODEL_HINT)
    assert rows(config, "leetcode_showings")[-1][:2] == (2, 2) and assignments(config)[1][3] == MODEL_HINT


def test_a_run_shows_the_exercise_the_user_was_given_if_it_chose_another(config, fake_web, model, fake_articles):
    practise(config, 1)
    tutor.advance(config, exercise_id=1, now=day(1))  # two-sum is now the current exercise
    conn = db.connect(config.db_path)
    chosen = exercise_of(VANGUARD[0], hint="A hint for the problem the run chose.", hint_source="model")
    leetcode.place(chosen, [], day(1).astimezone().date())

    settled = leetcode.settle(conn, chosen)
    conn.close()

    assert (settled.problem.id, settled.assignment_id, settled.track) == (TWO_SUM.id, 2, "amd")
    assert (settled.hint, settled.hint_source, settled.day, settled.assigned_on) == (TWO_SUM.hints[0], "catalog", 1, local(1))


def test_completing_during_a_run_is_kept_and_the_digest_says_so(config, fake_web, model, fake_articles, monkeypatch):
    pipeline.run(config, now=day(0))
    real = leetcode.hints_enabled

    def meanwhile(settings):  # the run has restored the exercise; the user completes it before the run records
        tutor.complete(config, exercise_id=1, now=day(1))
        return real(settings)

    monkeypatch.setattr(leetcode, "hints_enabled", meanwhile)
    pipeline.run(config, now=day(1))
    monkeypatch.setattr(leetcode, "hints_enabled", real)

    assert (shown(config)["problem_id"], shown(config)["day"], shown(config)["awaiting_completion"]) == (FIRST.id, 2, False)
    assert rows(config, "leetcode_outcomes") == [(1, "completed", day(1).isoformat())]
    pipeline.run(config, now=day(2))
    assert shown(config)["problem_id"] == TWO_SUM.id  # the completion was not lost to the run


def test_a_run_that_fails_leaves_the_exercise_and_its_days_as_they_were(config, fake_web, model, fake_articles, monkeypatch):
    pipeline.run(config, now=day(0))
    real = pipeline.write_outputs

    def no_disk(*args):
        raise OSError("disk full")

    monkeypatch.setattr(pipeline, "write_outputs", no_disk)
    with pytest.raises(OSError):
        pipeline.run(config, now=day(1))
    monkeypatch.setattr(pipeline, "write_outputs", real)

    assert table_count(config, "leetcode_showings") == 1 and tutor.status(config, now=day(1))["current"]["day"] == 1
    pipeline.run(config, now=day(1))
    assert (shown(config)["problem_id"], shown(config)["day"]) == (FIRST.id, 2)


def test_a_damaged_or_missing_database_is_reported_and_nothing_is_marked(config, config_file, capsys):
    code, out, _ = run_cli(capsys, ["mark", "complete", "--json", "--config", config_file])
    assert code == 2 and json.loads(out)["error"]["code"] == "no_exercise"

    config.db_path.parent.mkdir(parents=True)
    config.db_path.write_bytes(b"this is not a database" * 100)
    for action in (["mark", "complete"], ["next"]):
        code, out, err = run_cli(capsys, [*action, "--json", "--config", config_file])
        assert code == 1 and json.loads(out)["error"]["code"] == "failed" and "dailygrad:" in err
    assert config.db_path.read_bytes() == b"this is not a database" * 100


# --- a database from before exercises were kept


def earlier_database(config):
    """Three exercises on three days, as the version that assigned one a day left them, with marks and a hint turn."""
    conn = db.connect(config.db_path)
    with conn:
        for number, problem in enumerate((NEETCODE[0], AMD[0], VANGUARD[0])):
            run_id = db.record_run(conn, day(number).astimezone().date(), Path("digest.md"), [], day(number))
            exercise = exercise_of(problem, ("neetcode-150", "amd", "vanguard")[number], hint=f"Hint {number}.", hint_source="model")
            db.record_leetcode(conn, run_id, exercise, "test-model", day(number))
        db.mark_leetcode(conn, NEETCODE[0].id, day(0), solved=True)
        db.mark_leetcode(conn, AMD[0].id, day(1), confidence="needs-review")
        db.record_leetcode_turn(conn, 3, VANGUARD[0].id, "hint", None, "{}", None, day(2))
        conn.execute("DROP TABLE leetcode_showings")
        conn.execute("DROP TABLE leetcode_outcomes")
    conn.close()
    return {table: rows(config, table) for table in ("runs", "leetcode_assignments", "leetcode_progress", "leetcode_turns")}


def test_status_reads_an_earlier_database_as_it_is_and_its_newest_exercise_is_the_current_one(config):
    before = earlier_database(config)

    status = tutor.status(config, now=day(2))

    assert (status["active_exercise_id"], status["completion_pending"]) == (3, True)
    current = status["current"]
    assert (current["problem_id"], current["date"], current["day"], current["is_today"]) == (VANGUARD[0].id, local(2), 1, True)
    assert (status["progress"]["exercises"], status["progress"]["completed"], status["progress"]["skipped"]) == (3, 0, 0)
    assert status["next_track"]["id"] == "neetcode-150"  # the rotation is where it was
    conn = sqlite3.connect(config.db_path)
    tables = {name for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    conn.close()
    assert not {"leetcode_showings", "leetcode_outcomes"} & tables  # status only reads
    assert {table: rows(config, table) for table in before} == before


def test_an_earlier_database_keeps_everything_and_carries_its_newest_exercise_over(config, fake_web, model, fake_articles):
    before = earlier_database(config)

    digest, _ = pipeline.run(config, now=day(3))

    assert {table: rows(config, table) for table in before if table != "runs"} == {
        table: content for table, content in before.items() if table != "runs"
    }  # no row changed: not an assignment, a mark or an exchange
    assert rows(config, "runs")[:3] == before["runs"]
    carried = shown(config)
    assert (carried["problem_id"], carried["exercise_id"], carried["track"]) == (VANGUARD[0].id, 3, "vanguard")
    assert (carried["day"], carried["is_carryover"], carried["assigned_on"], carried["hint"]) == (2, True, local(2), "Hint 2.")
    assert "**Still in progress" in digest and len(model.hint_requests) == 0
    assert [(run, assignment) for run, assignment, _ in rows(config, "leetcode_showings")] == [(1, 1), (2, 2), (3, 3), (4, 3)]
    assert rows(config, "leetcode_outcomes") == []  # the two it replaced are history, not completions

    progress = tutor.status(config, now=day(3))["progress"]
    assert (progress["solved_in_code"], progress["needs_review"], progress["exercises"]) == (1, 1, 3)
    assert refused(lambda: tutor.complete(config, exercise_id=1, now=day(3))) == "stale_exercise"

    tutor.complete(config, exercise_id=3, now=day(3))
    pipeline.run(config, now=day(4))
    assert (shown(config)["problem_id"], shown(config)["track"]) == (NEETCODE[1].id, "neetcode-150")  # the fourth turn


def test_completing_is_enough_to_bring_an_earlier_database_up_to_date(config):
    before = earlier_database(config)

    result = tutor.complete(config, exercise_id=3, now=day(2))

    assert result["changed"] and result["exercise"]["days_shown"] == 1 and result["next_track"]["id"] == "neetcode-150"
    assert {table: rows(config, table) for table in before} == before
    assert len(rows(config, "leetcode_showings")) == 3 and rows(config, "leetcode_outcomes") == [(3, "completed", day(2).isoformat())]


# --- the command line


def test_mark_complete_and_next_report_as_json(config, fake_web, model, fake_articles, config_file, capsys):
    pipeline.run(config, now=day(0))
    capsys.readouterr()

    code, out, _ = run_cli(capsys, ["status", "--json", "--config", config_file])
    exercise = str(json.loads(out)["active_exercise_id"])
    code, out, _ = run_cli(capsys, ["mark", "complete", "--exercise", exercise, "--json", "--config", config_file])
    completed = json.loads(out)
    assert code == 0 and (completed["action"], completed["changed"], completed["exercise"]["problem_id"]) == ("complete", True, FIRST.id)
    assert completed["next_track"] == {"id": "amd", "name": "AMD"} and completed["completion_pending"] is False

    code, out, _ = run_cli(capsys, ["next", "--exercise", exercise, "--json", "--config", config_file])
    moved = json.loads(out)
    assert code == 0 and (moved["action"], moved["changed"], moved["active"]["problem_id"]) == ("next", True, TWO_SUM.id)
    assert "reference_solution" not in out and TWO_SUM.approach not in out

    for arguments, error in (
        (["mark", "complete", "--exercise", exercise], "stale_exercise"),  # completed, and another is current: fine...
        (["next", "--exercise", "99"], "unknown_exercise"),
        (["next", "--exercise", "abc"], "unknown_exercise"),
        (["mark", "complete", "--problem", FIRST.id], "stale_exercise"),
        (["mark", "attempted", "--exercise", "2"], "bad_arguments"),
    ):
        code, out, err = run_cli(capsys, [*arguments, "--json", "--config", config_file])
        if arguments[:2] == ["mark", "complete"] and arguments[2] == "--exercise":
            assert code == 0 and json.loads(out)["changed"] is False  # ...a repeat of a completion is not an error
            continue
        assert code == 2 and json.loads(out) == {"ok": False, "error": {"code": error, "message": err.strip().removeprefix("dailygrad: ")}}
    assert table_count(config, "runs") == 1 and len(assignments(config)) == 2


def test_the_plain_text_forms_say_what_happened_and_what_comes_next(config, fake_web, model, fake_articles, config_file, capsys):
    pipeline.run(config, now=day(0))
    capsys.readouterr()

    _, out, _ = run_cli(capsys, ["status", "--config", config_file])
    assert "Current exercise 1 (first shown" in out and "Awaiting completion: `dailygrad leetcode mark complete`" in out
    assert "Exercises: 1 assigned; 0 completed, 0 skipped." in out

    _, out, _ = run_cli(capsys, ["mark", "complete", "--config", config_file])
    assert out.startswith(f"{FIRST.title} (exercise 1) marked complete. This is not a mark that you solved it in code.")
    assert "The next digest moves on to the AMD track" in out
    _, out, _ = run_cli(capsys, ["mark", "complete", "--config", config_file])
    assert out.startswith(f"{FIRST.title} (exercise 1) was already complete.")
    _, out, _ = run_cli(capsys, ["status", "--config", config_file])
    assert "Completed: the next digest brings a new exercise" in out

    _, out, _ = run_cli(capsys, ["next", "--config", config_file])
    assert out.startswith(f"{FIRST.title} (exercise 1) stays completed.")
    assert f"The current exercise is now {TWO_SUM.title} (exercise 2, easy)" in out and TWO_SUM.statement in out
    _, out, _ = run_cli(capsys, ["next", "--config", config_file])
    assert out.startswith(f"{TWO_SUM.title} (exercise 2) recorded as skipped: not completed, and not solved.")
    _, out, _ = run_cli(capsys, ["next", "--exercise", "2", "--config", config_file])
    assert out.startswith(f"{TWO_SUM.title} (exercise 2) had been moved on from already. Nothing to change.")
    _, out, _ = run_cli(capsys, ["status", "--config", config_file])
    assert "Current exercise 3 (not in a digest yet)" in out and "Exercises: 3 assigned; 1 completed, 1 skipped." in out


# --- rendering


def test_only_an_exercise_from_an_earlier_day_or_one_already_closed_gets_a_line_of_its_own():
    def section(**fields):
        return render.render_digest(date(2026, 10, 12), [], [], None, exercise_of(TWO_SUM, "amd", **fields))

    new = section(assigned_on="2026-10-12", day=1)
    carried = section(assigned_on="2026-10-10", day=3)
    closed = section(assigned_on="2026-10-10", day=3, outcome="skipped")

    line = "**Still in progress — originally assigned October 10** (day 3).\n\n"
    assert carried == new.replace(TWO_SUM.statement, line + TWO_SUM.statement)  # one line added, nothing else changed
    assert "_Already skipped: the next digest brings a new exercise._" in closed and "Still in progress" not in closed
