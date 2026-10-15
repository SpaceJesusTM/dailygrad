"""Practice modes: the selected question sources as one pool, and coverage, loop and learning over it."""

import json
import os
import random
import sqlite3
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from dailygrad import cli, db, leetcode, pipeline, practice, render, tutor
from dailygrad.config import Config, load_config
from dailygrad.leetcode_catalog import load_catalog
from dailygrad.models import Exercise
from test_pipeline import FEED, fake_articles, fake_web, model, read_latest  # noqa: F401 (fixtures)

CATALOG = load_catalog()
TRACKS = ("neetcode-150", "amd", "vanguard")
START = datetime(2026, 10, 15, 14, 0, tzinfo=timezone.utc)  # 10:00 on October 15 in Toronto


def at(days: float) -> datetime:
    return START + timedelta(days=days)


def pool(*sources) -> list[str]:
    return [problem.id for problem in CATALOG.pool(sources)]


@pytest.fixture(autouse=True)
def toronto():
    """Days are Toronto's, as on the production host, whatever zone the machine running the tests is in."""
    before = os.environ.get("TZ")
    os.environ["TZ"] = "America/Toronto"
    time.tzset()
    yield
    if before is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = before
    time.tzset()


@pytest.fixture(autouse=True)
def seeded(monkeypatch):
    monkeypatch.setattr(practice, "shuffler", random.Random(20261015))


@pytest.fixture(autouse=True)
def catalog_once(monkeypatch):
    """The packaged catalog, read once: these tests simulate months of days, and each would read it several times."""
    for module in (leetcode, tutor):
        monkeypatch.setattr(module, "load_catalog", lambda: CATALOG)


@pytest.fixture
def config(tmp_path):
    config = Config(data_dir=str(tmp_path / "data"))
    config.leetcode.model_hints = False  # the catalog's hint: no model in these tests
    return config


@pytest.fixture
def config_file(tmp_path, config):
    path = tmp_path / "dailygrad.toml"
    path.write_text(f'data_dir = "{Path(config.data_dir).as_posix()}"\n[leetcode]\nmodel_hints = false\n')
    return str(path)


def show(config, when: datetime) -> Exercise | practice.Waiting | None:
    """The LeetCode part of a run at `when`, as pipeline.run does it, without the news, the lesson or a model."""
    today = when.astimezone().date()
    conn = db.connect(config.db_path)
    try:
        chosen = leetcode.daily_exercise(conn, today, config, when)
        with conn:
            run_id = db.record_run(conn, today, Path("digest.md"), [], when)
            return leetcode.record_showing(conn, run_id, chosen, config, today, when)
    finally:
        conn.close()


def complete(config, when: datetime) -> dict:
    return tutor.complete(config, now=when)


def skip(config, when: datetime) -> dict:
    return tutor.advance(config, now=when)


def practise(config, days: int, start: float = 0) -> list[str]:
    """Show and complete one exercise a day. Returns the problems, stopping early if the mode has none to give."""
    done = []
    for number in range(days):
        shown = show(config, at(start + number))
        if not isinstance(shown, Exercise):
            break
        complete(config, at(start + number))
        done.append(shown.problem.id)
    return done


def assigned(config) -> list[str]:
    conn = sqlite3.connect(config.db_path)
    try:
        return [problem for (problem,) in conn.execute("SELECT problem_id FROM leetcode_assignments ORDER BY id")]
    finally:
        conn.close()


def table(config, name) -> list[tuple]:
    conn = sqlite3.connect(config.db_path)
    try:
        return conn.execute(f"SELECT * FROM {name} ORDER BY 1").fetchall()
    finally:
        conn.close()


def run_cli(capsys, arguments):
    code = cli.main(["leetcode", *arguments])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def scheduled(id, problem, outcome=None, closed=None, encounter="first", review_number=None):
    """One exercise as the modes read it, for deciding without a database."""
    stamp = closed.isoformat() if closed else None
    return db.Scheduled(id, problem, outcome, stamp, "learning", ("amd",), encounter, None, review_number, None)


def learning(interval=7, limit=2, sources=("amd",)) -> practice.Settings:
    return practice.Settings(tuple(sources), "learning", interval, limit)


def local(days: float) -> date:
    return at(days).astimezone().date()


# --- sources: one pool


@pytest.mark.parametrize("sources", [["neetcode-150"], ["amd"], ["vanguard"], ["amd", "vanguard"], ["neetcode-150", "amd"], list(TRACKS)])
def test_coverage_assigns_every_problem_of_the_selected_sources_once_then_says_it_is_complete(config, sources):
    config.leetcode.sources = sources
    expected = pool(*sources)

    done = practise(config, len(expected) + 3)

    assert done == expected  # every one, each once, in the pool's order: easy first, topic by topic
    after = show(config, at(len(expected) + 5))
    assert isinstance(after, practice.Waiting) and after.state == "coverage_complete"
    names = " + ".join(CATALOG.sources[source].name for source in TRACKS if source in sources)
    assert after.message(CATALOG) == f"{names} coverage complete."
    assert assigned(config) == expected  # nothing was assigned again


def test_overlapping_sources_are_one_pool_and_a_shared_problem_comes_once(config):
    config.leetcode.sources = ["amd", "neetcode-150"]
    amd, neetcode = set(pool("amd")), set(pool("neetcode-150"))
    shared = amd & neetcode
    assert "two-sum" in shared and len(shared) > 1

    done = practise(config, 200)

    assert set(done) == amd | neetcode and len(done) == len(amd | neetcode) == len(set(done))
    statuses = tutor.status(config, now=at(200))
    amd_row = next(track for track in statuses["tracks"] if track["id"] == "amd")
    assert amd_row["shown"] == 17  # a problem is counted for every list that holds it
    coverage = statuses["practice"]["coverage"]
    assert [(part["id"], part["encountered"], part["problems"]) for part in coverage["by_source"]] == [
        ("neetcode-150", 150, 150), ("amd", 17, 17),
    ]  # fmt: skip


def test_an_exercise_keeps_every_list_it_is_on_and_says_which_was_selected(config):
    config.leetcode.sources = ["amd"]

    exercise = show(config, at(0))

    assert exercise.problem.id == "two-sum" and exercise.track == "amd"
    assert [source.id for source in exercise.sources] == ["neetcode-150", "amd"]  # membership is kept for reporting
    assert exercise.practice == {"mode": "coverage", "sources": ["amd"], "encounter": "first", "cycle": None, "review": None}


@pytest.mark.parametrize(
    "arguments, code",
    [
        (["--sources", "google"], "unknown_source"),
        (["--sources", "amd", "--", "x"], None),  # an argparse refusal: exit 2 before anything is read
        (["--mode", "random"], "unknown_mode"),
        (["--interval", "0"], "bad_interval"),
        (["--interval", "366"], "bad_interval"),
        (["--interval", "seven"], "bad_interval"),
        (["--max-reviews", "0"], "bad_max_reviews"),
        (["--max-reviews", "-1"], "bad_max_reviews"),
        (["--max-reviews", "forever"], "bad_max_reviews"),
        ([], "nothing_to_change"),
        (["--mode", "loop", "--interval", "0"], "bad_interval"),  # one bad value: nothing at all is changed
        (["--sources", "amd", "google", "--mode", "loop"], "unknown_source"),
    ],
)
def test_an_invalid_change_is_refused_whole_and_nothing_is_written(config, config_file, capsys, arguments, code):
    run_cli(capsys, ["practice", "set", "--sources", "vanguard", "--config", config_file])
    before = config.practice_preferences_path.read_bytes()

    if code is None:
        with pytest.raises(SystemExit) as exit_info:
            cli.main(["leetcode", "practice", "set", *arguments, "--json", "--config", config_file])
        assert exit_info.value.code == 2
    else:
        status, out, err = run_cli(capsys, ["practice", "set", *arguments, "--json", "--config", config_file])
        assert status == 2 and json.loads(out) == {"ok": False, "error": {"code": code, "message": err.strip().removeprefix("dailygrad: ")}}

    assert config.practice_preferences_path.read_bytes() == before
    assert practice.settings(config).sources == ("vanguard",) and practice.settings(config).mode == "coverage"


def test_an_empty_selection_is_refused_and_all_selects_every_source(config):
    with pytest.raises(practice.PracticeError) as error:
        practice.parse_changes(sources=[])
    assert error.value.code == "no_sources"

    assert practice.parse_changes(sources=["ALL"]) == {"sources": list(TRACKS)}
    assert practice.parse_changes(sources=["vanguard", "amd", "amd"]) == {"sources": ["amd", "vanguard"]}


def test_changing_sources_keeps_the_active_exercise_and_applies_to_the_next(config):
    show(config, at(0))  # contains-duplicate, from the default selection
    tutor.set_practice(config, practice.parse_changes(sources=["vanguard"]))

    kept = show(config, at(1))
    assert kept.problem.id == "contains-duplicate" and kept.assignment_id == 1  # not replaced, not skipped
    assert table(config, "leetcode_outcomes") == []

    complete(config, at(1))
    following = show(config, at(2))
    assert following.problem.id == pool("vanguard")[0] != "contains-duplicate"
    assert following.practice["sources"] == ["vanguard"]


def test_settings_persist_across_restarts_and_override_the_config_file(config, tmp_path):
    tutor.set_practice(config, practice.parse_changes(sources=["amd"], mode="learning", interval="3", max_reviews="unlimited"))

    path = tmp_path / "dailygrad.toml"
    path.write_text(f'data_dir = "{Path(config.data_dir).as_posix()}"\n[leetcode]\nsources = ["vanguard"]\nmode = "loop"\n')
    reloaded = practice.settings(load_config(path))  # another process, after an update, with a config file of its own

    assert (reloaded.sources, reloaded.mode, reloaded.review_interval_days, reloaded.max_reviews) == (("amd",), "learning", 3, None)
    assert reloaded.origin == dict.fromkeys(practice.SETTINGS, "preferences")
    assert json.loads(config.practice_preferences_path.read_text())["max_reviews"] == "unlimited"

    practice.reset(load_config(path))
    after = practice.settings(load_config(path))
    assert (after.sources, after.mode, after.origin["mode"]) == (("vanguard",), "loop", "config")


def test_changing_settings_never_changes_history(config):
    practise(config, 3)
    show(config, at(3))
    before = {name: table(config, name) for name in ("leetcode_assignments", "leetcode_outcomes", "leetcode_showings", "leetcode_schedule")}

    for changes in ({"sources": ["amd"]}, {"mode": "loop"}, {"mode": "learning", "review_interval_days": 1}, {"sources": list(TRACKS)}):
        tutor.set_practice(config, changes)
    practice.reset(config)

    assert {name: table(config, name) for name in before} == before


def test_a_damaged_settings_file_stops_new_assignments_but_never_guesses(config, config_file, capsys):
    show(config, at(0))
    complete(config, at(0))
    config.practice_preferences_path.write_text('{"version": 1, "mode": "sometimes"}')

    assert show(config, at(1)) is None  # the run says the exercise could not be prepared: nothing is assigned
    assert assigned(config) == ["contains-duplicate"]
    status = tutor.practice_status(config, now=at(1))
    assert "not a valid LeetCode practice settings file" in status["preferences_problem"]
    with pytest.raises(tutor.TutorError) as error:
        skip(config, at(1))
    assert error.value.code == "invalid_preferences" and table(config, "leetcode_outcomes")[0][1] == "completed"

    code, out, _ = run_cli(capsys, ["practice", "set", "--mode", "loop", "--json", "--config", config_file])
    result = json.loads(out)
    assert code == 0 and result["replaced_damaged_file"] is True and result["settings"]["mode"] == "loop"
    assert isinstance(show(config, at(2)), Exercise)


# --- coverage


def test_coverage_counts_history_from_before_practice_modes_as_its_first_pass(config):
    conn = db.connect(config.db_path)
    with conn:  # what the rotation left: exercises with no schedule row, the newest still open
        for number, problem_id in enumerate(("contains-duplicate", "two-sum", "valid-anagram")):
            problem = CATALOG.get(problem_id)
            run_id = db.record_run(conn, local(number), Path("d.md"), [], at(number))
            db.record_leetcode(conn, run_id, Exercise(problem, problem.tracks[0], CATALOG.sources_of(problem)), "m", at(number))
        db.close_leetcode(conn, 1, "completed", at(0))
        db.close_leetcode(conn, 2, "skipped", at(1))
    conn.close()

    carried = show(config, at(3))
    assert carried.problem.id == "valid-anagram" and carried.practice is None  # an exercise from before modes, kept
    complete(config, at(3))
    following = show(config, at(4))
    assert following.problem.id not in {"contains-duplicate", "two-sum", "valid-anagram"}
    assert following.practice["encounter"] == "first"
    assert tutor.practice_status(config, now=at(4))["coverage"]["pass"] == 1


def test_moving_on_when_coverage_is_complete_ends_the_exercise_and_assigns_nothing(config):
    config.leetcode.sources = ["amd"]
    practise(config, 16)
    show(config, at(16))  # the last AMD problem

    result = skip(config, at(16))

    assert result["changed"] and result["previous"]["outcome"] == "skipped" and result["active"] is None
    assert result["upcoming"] == {"state": "coverage_complete", "message": "AMD coverage complete.", "next_review_on": None}
    assert len(assigned(config)) == 17
    again = skip(config, at(16))  # asked again: nothing is left to skip or to assign
    assert again["changed"] is False and again["active"] is None and again["upcoming"]["state"] == "coverage_complete"


def test_a_fresh_coverage_pass_assigns_everything_again_and_keeps_all_history(config, config_file, capsys):
    tutor.set_practice(config, {"sources": ["amd"]})  # stored, so the command line's process sees it too
    practise(config, 17)
    before = {name: table(config, name) for name in ("leetcode_assignments", "leetcode_outcomes", "leetcode_showings")}
    database = config.db_path.read_bytes()

    code, out, _ = run_cli(capsys, ["practice", "restart-coverage", "--json", "--config", config_file])
    preview = json.loads(out)
    assert code == 0 and preview["dry_run"] and not preview["changed"] and preview["would_change"]
    assert preview["coverage"]["complete"] and config.db_path.read_bytes() == database  # a dry run touches nothing

    code, out, _ = run_cli(capsys, ["practice", "restart-coverage", "--confirm", "--json", "--config", config_file])
    restarted = json.loads(out)
    assert code == 0 and restarted["changed"] and restarted["history_kept"]
    assert (restarted["coverage"]["pass"], restarted["coverage"]["encountered"]) == (2, 0)
    assert {name: table(config, name) for name in before} == before  # only a marker was added

    again = practise(config, 20, start=20)
    assert again == pool("amd")  # the second pass, the same order again
    assert len(assigned(config)) == 34  # every exercise of both passes is kept
    code, out, _ = run_cli(capsys, ["practice", "restart-coverage", "--confirm", "--json", "--config", config_file])
    assert json.loads(out)["coverage"]["pass"] == 3


def test_restarting_coverage_with_an_exercise_open_counts_it_in_the_new_pass(config):
    config.leetcode.sources = ["amd"]
    practise(config, 3)
    open_now = show(config, at(3))

    assert tutor.restart_coverage(config, True, now=at(3))["changed"]
    assert tutor.restart_coverage(config, True, now=at(3))["changed"] is False  # the new pass has only that one in it

    kept = show(config, at(4))
    assert kept.assignment_id == open_now.assignment_id  # still the current exercise
    complete(config, at(4))
    rest = practise(config, 30, start=5)
    assert open_now.problem.id not in rest and len(rest) == 16


# --- loop


def test_a_loop_cycle_holds_every_problem_of_the_combined_pool_once(config):
    config.leetcode.sources, config.leetcode.mode = ["amd", "vanguard"], "loop"
    combined = set(pool("amd", "vanguard"))

    first = practise(config, len(combined))
    second = practise(config, len(combined), start=len(combined))

    assert set(first) == set(second) == combined  # the union, not one loop per source
    assert len(first) == len(second) == len(combined)  # no problem twice in a cycle
    assert first != second  # reshuffled
    assert second[0] != first[-1]  # and not the same problem twice in a row
    assert first != pool("amd", "vanguard")  # the first cycle is shuffled too
    cycles = db.cycles(db.connect(config.db_path))
    assert [(cycle.number, cycle.ended, list(cycle.problems)) for cycle in cycles] == [(1, "completed", first), (2, None, second)]


def test_the_cycle_and_its_progress_survive_a_restart_and_a_failed_run(config, monkeypatch):
    config.leetcode.sources, config.leetcode.mode = ["amd"], "loop"
    done = practise(config, 5)
    order = db.cycles(db.connect(config.db_path))[0].problems

    def broken(*args):
        raise OSError("disk full")

    monkeypatch.setattr(leetcode, "record", broken)
    with pytest.raises(OSError):
        show(config, at(5))  # a run that fails before recording its exercise
    monkeypatch.undo()
    monkeypatch.setattr(practice, "shuffler", random.Random(1))  # a restarted process, with other randomness

    rest = practise(config, 12, start=6)

    assert done + rest == list(order)  # neither reshuffled nor restarted
    conn = db.connect(config.db_path)
    assert len(db.cycles(conn)) == 1 and tutor.practice_status(config)["loop"]["cycle"]["assigned"] == 17
    conn.close()


def test_a_new_cycle_does_not_begin_with_the_problem_that_ended_the_last(config, monkeypatch):
    class Alternating:
        """Keeps the pool's order for the first cycle and reverses it for the next: the last would come first again."""

        def __init__(self):
            self.calls = 0

        def shuffle(self, items):
            self.calls += 1
            if self.calls % 2 == 0:
                items.reverse()

        def randrange(self, start, stop):
            return start

    monkeypatch.setattr(practice, "shuffler", Alternating())
    config.leetcode.sources, config.leetcode.mode = ["amd"], "loop"

    first = practise(config, 17)
    second = practise(config, 17, start=17)

    assert first == pool("amd") and second[0] != first[-1]
    assert second == [pool("amd")[-2], pool("amd")[-1], *reversed(pool("amd")[:-2])]  # the first two swapped


def test_completing_or_skipping_moves_a_cycle_on_and_showing_it_again_does_not(config):
    config.leetcode.sources, config.leetcode.mode = ["amd"], "loop"
    first = show(config, at(0))
    for number in (1, 2, 3):  # shown on three more days: still the first question of the cycle
        assert show(config, at(number)).assignment_id == first.assignment_id
    assert tutor.practice_status(config, now=at(3))["loop"]["cycle"]["assigned"] == 1

    result = skip(config, at(3))
    assert result["active"]["practice"]["cycle"] == {"number": 1, "position": 2, "size": 17}
    skip(config, at(3))
    rest = practise(config, 15, start=4)  # the rest of the cycle

    assert first.problem.id not in rest and len(rest) == len(set(rest)) == 15  # a skipped question is not given again in its cycle
    assert len(set(assigned(config))) == 17 and len(assigned(config)) == 17


def test_changing_sources_mid_cycle_keeps_the_active_exercise_then_starts_a_fresh_cycle(config):
    config.leetcode.sources, config.leetcode.mode = ["amd"], "loop"
    practise(config, 3)
    active = show(config, at(3))

    tutor.set_practice(config, {"sources": ["amd", "vanguard"]})
    assert show(config, at(4)).assignment_id == active.assignment_id  # the current exercise stays
    complete(config, at(4))
    following = show(config, at(5))

    cycles = db.cycles(db.connect(config.db_path))
    assert [(cycle.number, cycle.sources, cycle.ended) for cycle in cycles] == [
        (1, ("amd",), "sources_changed"), (2, ("amd", "vanguard"), None),
    ]  # fmt: skip
    assert following.practice["cycle"] == {"number": 2, "position": 1, "size": len(pool("amd", "vanguard"))}
    assert len(table(config, "leetcode_schedule")) == 5  # the first cycle's exercises are history, kept
    assert sum(row[4] == cycles[0].id for row in table(config, "leetcode_schedule")) == 4


def test_two_runs_choosing_at_once_begin_one_cycle(config):
    config.leetcode.sources, config.leetcode.mode = ["amd"], "loop"
    conns = [db.connect(config.db_path), db.connect(config.db_path)]
    try:
        chosen = [leetcode.daily_exercise(conn, local(0), config, at(0)) for conn in conns]
        assert chosen[0].problem.id == chosen[1].problem.id and len(db.cycles(conns[0])) == 1
        with conns[1]:
            run_id = db.record_run(conns[1], local(0), Path("d.md"), [], at(0))
            leetcode.record_showing(conns[1], run_id, chosen[1], config, local(0), at(0))
        with conns[0]:
            run_id = db.record_run(conns[0], local(0), Path("d.md"), [], at(0))
            settled = leetcode.record_showing(conns[0], run_id, chosen[0], config, local(0), at(0))
    finally:
        for conn in conns:
            conn.close()
    assert settled.assignment_id == 1 and assigned(config) == [chosen[0].problem.id]  # one exercise, shown by both


# --- learning: the schedule, decided without a database


def test_a_review_falls_due_one_interval_after_the_completion_and_not_a_day_before():
    history = [scheduled(1, "two-sum", "completed", at(0))]

    for days in range(7):
        early = practice.choose(CATALOG, learning(), practice.Snapshot(history), local(days))
        assert early.problem.id != "two-sum" and early.encounter == "first"
    due = practice.choose(CATALOG, learning(), practice.Snapshot(history), local(7))

    assert (due.problem.id, due.encounter, due.review_number, due.due_on) == ("two-sum", "review", 1, "2026-10-22")


def test_a_late_review_sets_the_next_from_the_day_it_was_actually_completed():
    history = [
        scheduled(1, "two-sum", "completed", at(0)),
        scheduled(2, "two-sum", "completed", at(9), encounter="review", review_number=1),  # due on day 7, done on day 9
    ]

    assert practice.choose(CATALOG, learning(), practice.Snapshot(history), local(15)).problem.id != "two-sum"
    due = practice.choose(CATALOG, learning(), practice.Snapshot(history), local(16))
    assert (due.problem.id, due.review_number, due.due_on) == ("two-sum", 2, local(16).isoformat())


def test_reviews_stop_after_the_limit_and_continue_without_one():
    history = [
        scheduled(1, "two-sum", "completed", at(0)),
        scheduled(2, "two-sum", "completed", at(7), encounter="review", review_number=1),
        scheduled(3, "two-sum", "completed", at(14), encounter="review", review_number=2),
    ]
    state = practice.Snapshot(history)

    assert practice.choose(CATALOG, learning(limit=2), state, local(60)).problem.id != "two-sum"  # retired after two
    third = practice.choose(CATALOG, learning(limit=3), state, local(21))
    assert (third.problem.id, third.review_number) == ("two-sum", 3)
    unlimited = practice.choose(CATALOG, learning(limit=None), state, local(400))
    assert (unlimited.problem.id, unlimited.review_number) == ("two-sum", 3)


def test_the_longest_due_review_comes_first_then_the_pools_order():
    later, earlier = pool("amd")[5], pool("amd")[9]
    history = [
        scheduled(1, later, "completed", at(3)),
        scheduled(2, earlier, "completed", at(1)),
        scheduled(3, pool("amd")[0], "completed", at(3)),
    ]
    state = practice.Snapshot(history)

    assert practice.choose(CATALOG, learning(), state, local(20)).problem.id == earlier  # due on day 8, not 10
    same_day = practice.choose(CATALOG, learning(), practice.Snapshot(history[:1] + history[2:]), local(20))
    assert same_day.problem.id == pool("amd")[0]  # both due on day 10: the pool's order decides


def test_a_skip_is_not_a_completed_review_and_sets_the_problem_aside_for_one_interval():
    history = [
        scheduled(1, "two-sum", "completed", at(0)),
        scheduled(2, "two-sum", "skipped", at(7), encounter="review", review_number=1),
    ]
    state = practice.Snapshot(history)

    assert practice.choose(CATALOG, learning(), state, local(7)).problem.id != "two-sum"  # not straight back
    assert practice.choose(CATALOG, learning(), state, local(13)).problem.id != "two-sum"
    again = practice.choose(CATALOG, learning(), state, local(14))
    assert (again.problem.id, again.review_number) == ("two-sum", 1)  # the skip used up nothing


def test_a_skipped_new_problem_waits_one_interval_and_then_comes_after_those_never_offered():
    first, second = pool("amd")[:2]
    state = practice.Snapshot([scheduled(1, first, "skipped", at(0))])

    assert practice.choose(CATALOG, learning(), state, local(0)).problem.id == second
    assert practice.choose(CATALOG, learning(), state, local(7)).problem.id == second  # never offered comes first
    only = practice.Snapshot([scheduled(1, first, "skipped", at(0))] + [
        scheduled(n + 2, problem, "completed", at(1)) for n, problem in enumerate(pool("amd")[1:])
    ])  # fmt: skip
    assert practice.choose(CATALOG, learning(interval=30), only, local(6)).state == "caught_up"
    assert practice.choose(CATALOG, learning(interval=30), only, local(30)).problem.id == first


def test_with_nothing_due_and_nothing_new_practice_waits_for_the_next_review():
    history = [scheduled(n + 1, problem, "completed", at(n % 3)) for n, problem in enumerate(pool("amd"))]

    waiting = practice.choose(CATALOG, learning(), practice.Snapshot(history), local(5))

    assert (waiting.state, waiting.next_review_on) == ("caught_up", "2026-10-22")
    assert waiting.message(CATALOG) == "No reviews due. Next review: October 22."


def test_when_every_review_is_done_learning_says_so():
    history = [scheduled(n + 1, problem, "completed", at(0)) for n, problem in enumerate(pool("amd"))]
    history += [
        scheduled(n + 18, problem, "completed", at(7), encounter="review", review_number=1) for n, problem in enumerate(pool("amd"))
    ]

    waiting = practice.choose(CATALOG, learning(limit=1), practice.Snapshot(history), local(30))

    assert (waiting.state, waiting.next_review_on) == ("learning_complete", None)
    assert waiting.message(CATALOG) == "AMD: every question has had its 1 review. No reviews are left."


def test_reviews_count_only_learning_reviews_completed_not_repeats_in_other_modes():
    history = [
        scheduled(1, "two-sum", "completed", at(0), encounter="first"),
        scheduled(2, "two-sum", "completed", at(1), encounter="repeat"),  # a loop cycle's repeat: practice, not a review
        scheduled(3, "two-sum", "completed", at(2), encounter="repeat"),
    ]

    due = practice.choose(CATALOG, learning(limit=1), practice.Snapshot(history), local(9))

    assert (due.problem.id, due.review_number) == ("two-sum", 1)  # due a week after the latest completion


def test_calendar_days_are_torontos_at_the_day_boundary():
    late_evening = datetime(2026, 10, 16, 3, 30, tzinfo=timezone.utc)  # 23:30 on October 15 in Toronto
    state = practice.Snapshot([scheduled(1, "two-sum", "completed", late_evening)])

    assert practice.local_day(late_evening.isoformat()) == date(2026, 10, 15)
    assert practice.choose(CATALOG, learning(), state, date(2026, 10, 21)).problem.id != "two-sum"
    assert practice.choose(CATALOG, learning(), state, date(2026, 10, 22)).problem.id == "two-sum"


# --- learning: in runs


def test_learning_with_runs_reviews_on_the_due_day_and_labels_the_review(config):
    config.leetcode.sources, config.leetcode.mode = ["amd"], "learning"
    config.leetcode.review_interval_days, config.leetcode.max_reviews = 7, 2

    first = practise(config, 7)  # October 15 to 21: seven new problems
    review = show(config, at(7))

    assert review.problem.id == first[0] and review.practice["encounter"] == "review"
    assert review.practice["review"] == {"number": 1, "limit": 2, "due_on": "2026-10-22"}
    assert review.review is True and render.practice_label(review.practice) == "Learning practice · review 1 of 2"
    for number in (8, 9):  # shown again while it is open: still review 1, not three reviews
        assert show(config, at(number)).assignment_id == review.assignment_id
    complete(config, at(9))
    overview = tutor.practice_status(config, now=at(9))["learning"]
    assert overview["review_interval_days"] == 7 and overview["max_reviews"] == 2
    assert (overview["due_now"], overview["next_review_on"]) == (2, "2026-10-25")  # the 2nd and 3rd are due; the 4th next


def test_learning_boundary_in_runs_just_before_and_after_midnight(config):
    config.leetcode.sources, config.leetcode.mode = ["amd"], "learning"
    config.leetcode.review_interval_days = 1
    show(config, datetime(2026, 10, 16, 3, 0, tzinfo=timezone.utc))  # 23:00 on October 15
    complete(config, datetime(2026, 10, 16, 3, 30, tzinfo=timezone.utc))

    still_15th = show(config, datetime(2026, 10, 16, 3, 50, tzinfo=timezone.utc))
    assert still_15th.problem.id == "two-sum" and still_15th.outcome == "completed"  # that day's exercise, done
    skip(config, datetime(2026, 10, 16, 3, 55, tzinfo=timezone.utc))  # the next one now: two-sum is not due until the 16th
    assert assigned(config)[-1] != "two-sum"
    complete(config, datetime(2026, 10, 16, 3, 56, tzinfo=timezone.utc))
    on_16th = show(config, datetime(2026, 10, 16, 4, 30, tzinfo=timezone.utc))  # 00:30 on October 16
    assert on_16th.problem.id == "two-sum" and on_16th.practice["review"]["number"] == 1


def test_no_review_due_is_reported_in_the_digest_without_degrading_it(config, fake_web, model, fake_articles):
    config.rss.feeds, config.final_story_count = [FEED], 3
    config.leetcode.sources, config.leetcode.mode = ["amd"], "learning"
    conn = db.connect(config.db_path)
    with conn:  # every AMD problem completed on October 15
        for problem_id in pool("amd"):
            problem = CATALOG.get(problem_id)
            run_id = db.record_run(conn, local(0), Path("d.md"), [], at(0))
            assignment = db.record_leetcode(conn, run_id, Exercise(problem, "amd", CATALOG.sources_of(problem)), "m", at(0))
            db.close_leetcode(conn, assignment, "completed", at(0))
    conn.close()

    digest, model_ok = pipeline.run(config, now=at(3))

    document = read_latest(config)
    assert model_ok and document["status"] == "ok" and document["lesson"] is not None  # the rest of the digest is whole
    assert document["leetcode"] is None and document["leetcode_practice"] == {
        "mode": "learning", "sources": [{"id": "amd", "name": "AMD"}], "state": "caught_up",
        "message": "No reviews due. Next review: October 22.", "next_review_on": "2026-10-22",
    }  # fmt: skip
    assert "## LeetCode Micro-Lesson\n\n_No reviews due. Next review: October 22._\n" in digest
    assert len(assigned(config)) == 17  # nothing was assigned early


# --- a fresh practice session: restart-questions


HISTORY = ("runs", "leetcode_assignments", "leetcode_outcomes", "leetcode_showings", "leetcode_schedule",
           "leetcode_progress", "leetcode_turns", "leetcode_coverage_passes")  # fmt: skip


def test_restarting_questions_makes_every_question_eligible_again_and_keeps_all_history(config, config_file, capsys, monkeypatch):
    tutor.set_practice(config, {"sources": ["amd"]})  # stored, so the command line's process sees it too
    practise(config, 17)
    assert isinstance(show(config, at(17)), practice.Waiting)  # coverage complete
    tutor.mark(config, "comfortable", pool("amd")[0], now=at(17))
    tutor.restart_coverage(config, True, now=at(17))  # a pass of its own, which the session also ends
    before = {name: table(config, name) for name in HISTORY}
    settings_file = config.practice_preferences_path.read_bytes()
    database = config.db_path.read_bytes()

    def no_model(*args, **kwargs):
        raise AssertionError("a restart uses no model")

    monkeypatch.setattr(leetcode.llm, "chat_json", no_model)
    monkeypatch.setattr(pipeline, "run", no_model)

    code, out, _ = run_cli(capsys, ["practice", "restart-questions", "--json", "--config", config_file])
    preview = json.loads(out)
    assert code == 0 and preview["dry_run"] and not preview["changed"] and preview["would_change"] and preview["epoch"] == 1
    assert config.db_path.read_bytes() == database  # a dry run touches nothing

    code, out, _ = run_cli(capsys, ["practice", "restart-questions", "--confirm", "--json", "--config", config_file])
    restarted = json.loads(out)
    assert code == 0 and restarted["ok"] and restarted["changed"] and restarted["history_kept"]
    assert restarted["action"] == "restart_questions" and restarted["epoch"] == 2 and restarted["session"]["exercises"] == 0
    assert restarted["catalog_problems"] == len(CATALOG.problems)
    assert restarted["sources"] == [{"id": "amd", "name": CATALOG.sources["amd"].name}]
    assert restarted["pool"] == {"problems": 17, "sources": ["amd"]}
    assert restarted["settings"] == preview["settings"] == {"sources": ["amd"], "mode": "coverage", "review_interval_days": 7,
                                                             "max_reviews": 3}  # fmt: skip
    assert restarted["active"] is None and restarted["active_exercise_id"] is None
    assert restarted["upcoming"]["state"] == "exercise"
    assert {name: table(config, name) for name in HISTORY} == before  # only a marker was added
    assert config.practice_preferences_path.read_bytes() == settings_file  # the settings are untouched
    assert [row[2:] for row in table(config, "leetcode_practice_resets")] == [(17, 0)]

    assert practise(config, 20, start=20) == pool("amd")  # every question again, from the first
    status = tutor.status(config, now=at(40))
    assert (status["progress"]["exercises"], status["progress"]["completed"]) == (34, 34)  # statistics count every session
    assert status["progress"]["comfortable"] == 1  # and the marks are kept
    assert status["practice"]["session"]["epoch"] == 2 and status["practice"]["coverage"]["pass"] == 1


def test_a_restart_frees_every_source_not_only_the_selected_ones(config):
    tutor.set_practice(config, {"sources": ["vanguard"]})
    practise(config, 40)
    tutor.set_practice(config, {"sources": ["amd"]})
    practise(config, 20, start=40)
    assert isinstance(show(config, at(60)), practice.Waiting)  # both covered

    assert tutor.restart_questions(config, True, now=at(60))["pool"] == {"problems": 17, "sources": ["amd"]}
    tutor.set_practice(config, {"sources": ["vanguard"]})  # a source that was not selected at the restart

    assert practise(config, 40, start=61) == pool("vanguard")
    tutor.set_practice(config, {"sources": ["amd", "vanguard"]})
    rest = practise(config, 40, start=100)
    assert rest == [problem for problem in pool("amd", "vanguard") if problem not in pool("vanguard")]


def test_restarting_questions_in_loop_mode_ends_the_cycle_and_the_next_exercise_shuffles_a_fresh_one(config):
    config.leetcode.sources, config.leetcode.mode = ["amd"], "loop"
    done = practise(config, 5)
    old_order = db.cycles(db.connect(config.db_path))[0].problems

    result = tutor.restart_questions(config, True, now=at(5))
    assert result["changed"] and result["upcoming"]["state"] == "new_cycle"
    status = tutor.practice_status(config, now=at(5))
    assert status["loop"] == {"cycle": None, "cycles_completed": 0} and status["session"]["epoch"] == 2

    fresh = practise(config, 17, start=6)
    assert sorted(fresh) == sorted(pool("amd"))  # the whole pool, the five done before included
    assert fresh[0] != done[-1] and fresh != list(old_order)
    cycles = db.cycles(db.connect(config.db_path))
    assert [(cycle.number, cycle.ended) for cycle in cycles] == [(1, "reset"), (1, None)]  # numbered anew in the session
    assert list(cycles[1].problems) == fresh
    assert sum(row[4] == cycles[0].id for row in table(config, "leetcode_schedule")) == 5  # the old cycle's exercises are kept


def test_after_a_restart_learning_counts_no_earlier_completion_or_review():
    first, second, third = pool("amd")[:3]
    history = [
        scheduled(1, first, "completed", at(0)),
        scheduled(2, first, "completed", at(7), encounter="review", review_number=1),  # its one review done
        scheduled(3, second, "completed", at(8)),  # its review falls due on day 15
    ]
    assert practice.choose(CATALOG, learning(limit=1), practice.Snapshot(history), local(9)).problem.id == third

    reset = [db.Reset(1, at(9).isoformat(), 3, 0)]
    fresh = practice.choose(CATALOG, learning(limit=1), practice.Snapshot(history, resets=reset), local(9))
    assert (fresh.problem.id, fresh.encounter) == (first, "repeat")  # reintroduced from the pool's first, known as seen before

    history.append(scheduled(4, first, "completed", at(9), encounter="repeat"))
    later = practice.Snapshot(history, resets=reset)
    due = practice.choose(CATALOG, learning(limit=1), later, local(16))
    assert (due.problem.id, due.review_number, due.due_on) == (first, 1, local(16).isoformat())  # from the new completion
    overview = practice.overview(CATALOG, learning(limit=1), later, local(10), None)["learning"]
    assert (overview["new_remaining"], overview["scheduled"], overview["reviews_complete"]) == (16, 1, 0)


def test_a_review_in_progress_at_a_restart_is_the_new_sessions_first_completion():
    first = pool("amd")[0]
    history = [
        scheduled(1, first, "completed", at(0)),
        scheduled(2, first, "completed", at(8), encounter="review", review_number=1),  # open when the session began
    ]
    state = practice.Snapshot(history, resets=[db.Reset(1, at(7).isoformat(), 1, 0)])

    due = practice.choose(CATALOG, learning(limit=1), state, local(15))

    assert (due.problem.id, due.review_number) == (first, 1)  # its one review is still owed, a week after it


def test_learning_with_runs_after_a_restart_reintroduces_questions_before_old_reviews(config):
    config.leetcode.sources, config.leetcode.mode = ["amd"], "learning"
    config.leetcode.review_interval_days, config.leetcode.max_reviews = 7, 2
    first = practise(config, 7)
    review = show(config, at(7))
    assert review.practice["encounter"] == "review" and review.problem.id == first[0]

    tutor.restart_questions(config, True, now=at(7))
    complete(config, at(7))  # the review in progress, completed in the new session
    following = practise(config, 6, start=8)
    again = show(config, at(14))

    assert following == pool("amd")[1:7]  # reintroduced, not reviewed: nothing was completed in this session
    assert all(entry == "repeat" for (*_, entry, _, _, _, _) in table(config, "leetcode_schedule")[8:14])
    assert (again.problem.id, again.practice["review"]) == (first[0], {"number": 1, "limit": 2, "due_on": "2026-10-29"})


@pytest.mark.parametrize("mode", ["coverage", "loop", "learning"])
def test_the_exercise_in_progress_stays_through_a_restart_and_is_not_given_straight_back(config, mode):
    config.leetcode.sources, config.leetcode.mode = ["amd"], mode
    practise(config, 3)
    open_now = show(config, at(3))

    result = tutor.restart_questions(config, True, now=at(3))
    assert result["changed"] and result["active_exercise_id"] == open_now.assignment_id
    assert result["active"]["problem_id"] == open_now.problem.id and result["session"]["exercises"] == 1
    assert tutor.restart_questions(config, True, now=at(3))["changed"] is False  # the session holds only that one

    assert show(config, at(4)).assignment_id == open_now.assignment_id  # still the current exercise
    assert len(table(config, "leetcode_outcomes")) == 3  # the restart completed and skipped nothing
    following = skip(config, at(4))["active"]
    assert following["problem_id"] != open_now.problem.id
    if mode == "coverage":
        rest = practise(config, 30, start=5)
        assert open_now.problem.id not in rest and len(rest) == 16  # it counts as the new pass's first


def test_restarting_again_begins_another_session_and_every_session_lasts_across_processes(config, config_file, capsys):
    tutor.set_practice(config, {"sources": ["amd"]})
    code, out, _ = run_cli(capsys, ["practice", "restart-questions", "--confirm", "--json", "--config", config_file])
    assert code == 0 and json.loads(out)["changed"] is False and not config.db_path.exists()  # nothing to restart
    practise(config, 2)

    def restart():
        code, out, _ = run_cli(capsys, ["practice", "restart-questions", "--confirm", "--json", "--config", config_file])
        assert code == 0
        return json.loads(out)

    assert (restart()["changed"], restart()["changed"]) == (True, False)  # the second found an empty session
    assert practise(config, 2, start=2) == pool("amd")[:2]
    assert restart()["epoch"] == 3
    assert len(table(config, "leetcode_practice_resets")) == 2 and len(assigned(config)) == 4

    code, out, _ = run_cli(capsys, ["practice", "--json", "--config", config_file])  # a new process, reading what is stored
    assert json.loads(out)["session"]["epoch"] == 3 and json.loads(out)["coverage"]["encountered"] == 0
    assert practise(config, 1, start=4) == pool("amd")[:1]
    assert tutor.restart_coverage(config, True, now=at(5))["coverage"]["pass"] == 2  # passes count within the session


def test_restart_questions_in_plain_text(config, config_file, capsys):
    run_cli(capsys, ["practice", "set", "--sources", "amd", "--config", config_file])
    empty = run_cli(capsys, ["practice", "restart-questions", "--config", config_file])[1]
    assert "has nothing in it yet, so a restart would change nothing" in empty
    practise(config, 2)
    shown = show(config, at(2))

    code, out, _ = run_cli(capsys, ["practice", "restart-questions", "--config", config_file])
    assert code == 0 and "Practice session 1: 3 exercises assigned. A restart begins session 2" in out
    assert "Dry run: nothing was changed. To restart: dailygrad leetcode practice restart-questions --confirm" in out

    code, out, _ = run_cli(capsys, ["practice", "restart-questions", "--confirm", "--config", config_file])
    assert code == 0 and out.startswith("Practice session 2 begun: every question is eligible again (17 problems from AMD")
    assert f"Exercise {shown.assignment_id} ({shown.problem.title}) stays current" in out
    again = run_cli(capsys, ["practice", "restart-questions", "--config", config_file])[1]
    assert "Practice session 2 has nothing in it yet but the exercise in progress, so a restart would change nothing" in again
    assert "Session:   2, since 2026-10-" in run_cli(capsys, ["practice", "--config", config_file])[1]


# --- concurrency


def test_settings_changed_during_a_run_apply_to_what_it_records(config, monkeypatch):
    config.leetcode.model_hints = True
    real = leetcode.write_hint

    def meanwhile(problem, settings):  # while the run is at work on the model, the user switches to Vanguard
        tutor.set_practice(config, {"sources": ["vanguard"]})
        return problem.hints[0], "model"

    monkeypatch.setattr(leetcode, "write_hint", meanwhile)
    shown = show(config, at(0))
    monkeypatch.setattr(leetcode, "write_hint", real)

    assert shown.problem.id == pool("vanguard")[0] != "contains-duplicate"
    assert (shown.hint, shown.hint_source) == (shown.problem.hints[0], "catalog")  # the model's hint was for the other
    assert assigned(config) == [pool("vanguard")[0]] and shown.practice["sources"] == ["vanguard"]


def test_a_restart_during_a_run_applies_to_what_it_records(config, monkeypatch):
    config.leetcode.sources = ["amd"]
    practise(config, 3)
    config.leetcode.model_hints = True
    real = leetcode.write_hint

    def meanwhile(problem, settings):  # while the run is at work on the model, the user starts every question over
        tutor.restart_questions(config, True, now=at(3))
        return problem.hints[0], "model"

    monkeypatch.setattr(leetcode, "write_hint", meanwhile)
    shown = show(config, at(3))
    monkeypatch.setattr(leetcode, "write_hint", real)

    assert shown.problem.id == pool("amd")[0] and shown.hint_source == "catalog"  # the session's first, not the 4th
    assert assigned(config) == [*pool("amd")[:3], pool("amd")[0]]


def test_concurrent_changes_to_different_settings_all_survive(config):
    changes = [{"sources": ["amd"]}, {"mode": "learning"}, {"review_interval_days": 3}, {"max_reviews": "unlimited"}] * 5
    threads = [threading.Thread(target=practice.change, args=(config, change)) for change in changes]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    current = practice.settings(config)
    assert (current.sources, current.mode, current.review_interval_days, current.max_reviews) == (("amd",), "learning", 3, None)


# --- reading never writes


def test_status_and_practice_read_without_creating_or_changing_anything(config, config_file, capsys):
    code, out, _ = run_cli(capsys, ["practice", "--json", "--config", config_file])
    assert code == 0 and not Path(config.data_dir).exists()  # nothing is created to answer

    config.leetcode.mode = "loop"
    show(config, at(0))
    files = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in Path(config.data_dir).rglob("*") if path.is_file()}

    for arguments in (["practice", "--json"], ["practice", "show"], ["status", "--json"], ["practice", "restart-coverage"],
                      ["practice", "restart-questions"]):
        assert run_cli(capsys, [*arguments, "--config", config_file])[0] == 0
    tutor.practice_status(config, now=at(400))

    after = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in Path(config.data_dir).rglob("*") if path.is_file()}
    assert after == files


def test_a_database_from_before_practice_modes_is_read_as_it_is_then_gains_the_tables(config):
    conn = db.connect(config.db_path)
    with conn:
        problem = CATALOG.get("two-sum")
        db.record_leetcode(conn, 0, Exercise(problem, "amd", CATALOG.sources_of(problem)), "m", at(0))
        for name in ("leetcode_schedule", "leetcode_cycles", "leetcode_coverage_passes"):
            conn.execute(f"DROP TABLE {name}")
    conn.close()

    status = tutor.practice_status(config, now=at(0))
    assert status["coverage"]["encountered"] == 1 and status["active"]["problem_id"] == "two-sum"
    conn = sqlite3.connect(config.db_path)
    tables = {name for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    columns = [row[1] for row in conn.execute("PRAGMA table_info(leetcode_assignments)")]
    conn.close()
    assert "leetcode_schedule" not in tables  # reading changed nothing
    assert columns == ["id", "run_id", "problem_id", "track", "review", "hint", "hint_source", "model", "created_at"]  # unchanged

    db.connect(config.db_path).close()
    db.connect(config.db_path).close()  # opening again is a no-op
    conn = sqlite3.connect(config.db_path)
    tables = {name for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    conn.close()
    assert {"leetcode_schedule", "leetcode_cycles", "leetcode_coverage_passes", "leetcode_practice_resets"} <= tables


# --- the command line


def test_practice_show_and_set_report_as_json(config, config_file, capsys):
    code, out, _ = run_cli(capsys, ["practice", "set", "--sources", "amd", "neetcode-150", "--mode", "learning", "--interval", "7",
                                    "--max-reviews", "3", "--json", "--config", config_file])  # fmt: skip
    result = json.loads(out)
    assert code == 0 and result["ok"] and result["changed"] and result["action"] == "set"
    assert result["settings"] == {"sources": ["neetcode-150", "amd"], "mode": "learning", "review_interval_days": 7, "max_reviews": 3}
    assert result["active_exercise_id"] is None and result["replaced_damaged_file"] is False

    code, out, _ = run_cli(capsys, ["practice", "set", "--mode", "learning", "--json", "--config", config_file])
    assert code == 0 and json.loads(out)["changed"] is False

    code, out, _ = run_cli(capsys, ["practice", "--json", "--config", config_file])
    shown = json.loads(out)
    assert list(shown) == [
        "ok", "enabled", "settings", "from", "modes", "available_sources", "pool", "active_exercise_id", "session", "coverage",
        "loop", "learning", "upcoming", "preferences_file", "preferences_problem", "active",
    ]  # fmt: skip
    assert shown["modes"] == ["coverage", "loop", "learning"] and shown["pool"]["problems"] == len(pool("neetcode-150", "amd"))
    assert [(source["id"], source["problems"], source["selected"]) for source in shown["available_sources"]] == [
        ("neetcode-150", 150, True), ("amd", 17, True), ("vanguard", 32, False),
    ]  # fmt: skip

    code, out, _ = run_cli(capsys, ["practice", "reset", "--json", "--config", config_file])
    assert code == 0 and json.loads(out)["settings"]["mode"] == "coverage" and not config.practice_preferences_path.exists()


def test_practice_in_plain_text(config, config_file, capsys):
    config.leetcode.mode = "loop"
    run_cli(capsys, ["practice", "set", "--mode", "loop", "--sources", "amd", "--config", config_file])
    shown = show(config, at(0))

    code, out, _ = run_cli(capsys, ["practice", "--config", config_file])

    assert code == 0 and "Sources:           AMD  (set here)" in out and "Mode:              loop  (set here)" in out
    assert "Loop:      cycle 1, 1 of 17 assigned; 0 cycles completed" in out
    assert f"Current exercise 1: {shown.problem.title}. It stays until you complete or skip it" in out
