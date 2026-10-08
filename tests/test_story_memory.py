"""Resetting story memory: the command, and its effect on later runs. Sources and the model are faked."""

from datetime import timedelta

import pytest

from conftest import NOW
from dailygrad import cli, db, history, pipeline
from test_pipeline import (  # noqa: F401 (fixtures)
    MODEL_FAILED_NOTE, SCHEDULE, config, fake_articles, fake_web, history_files, lesson_rows, model, read_latest,
    shown_titles, table_count,
)  # fmt: skip

FIRST_THREE = ["Model X released", "Running LLMs on a laptop", "Sparse attention"]  # what the fake model picks first


def run(config, minutes=0):
    digest, ok = pipeline.run(config, now=NOW + timedelta(minutes=minutes))
    return sorted(story["title"] for story in read_latest(config)["stories"]), ok


def reset(config):
    conn = db.connect(config.db_path)
    try:
        return db.reset_story_memory(conn, NOW)
    finally:
        conn.close()


def query(config, sql):
    conn = db.connect(config.db_path)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def test_stories_return_after_a_reset_and_are_then_excluded_again(config, fake_web, model, fake_articles):
    first, _ = run(config)
    second, _ = run(config, minutes=10)
    assert first == FIRST_THREE and not set(first) & set(second)  # before a reset nothing is repeated

    assert reset(config) == 6
    third, _ = run(config, minutes=20)
    assert third == first  # the same shortlist as the first run, so the same choice

    fourth, _ = run(config, minutes=30)
    assert fourth == second and not set(third) & set(fourth)  # shown since the reset, so excluded as usual
    fifth, _ = run(config, minutes=40)
    assert fifth == []  # all six have now been shown again


def test_a_reset_keeps_runs_archives_summaries_and_the_curriculum(config, fake_web, model, fake_articles):
    run(config)
    archives = {path: path.read_bytes() for path in history_files(config)}
    summaries = query(config, "SELECT item_id, run_id, what_happened FROM summaries ORDER BY item_id")
    items = query(config, "SELECT id, url_key, shown_run_id FROM items ORDER BY id")
    assert len(archives) == 2 and len(summaries) == 3

    reset(config)
    titles, ok = run(config, minutes=10)

    assert ok and titles == FIRST_THREE
    assert all(path.read_bytes() == content for path, content in archives.items())  # the first run's archive
    assert len(history_files(config)) == 4  # and the new run has its own
    assert query(config, "SELECT item_id, run_id, what_happened FROM summaries ORDER BY item_id") == summaries
    assert query(config, "SELECT id, url_key, shown_run_id FROM items ORDER BY id") == items
    assert table_count(config, "runs") == 2 and read_latest(config)["run_id"] == 2
    # The three stories' second showing, each with the summary written for it.
    assert query(config, "SELECT run_id, COUNT(*), COUNT(what_happened) FROM repeat_showings") == [(2, 3, 3)]
    assert history.find_run(config, 1, None)["run_id"] == 1  # the first run is still retrievable


def test_a_reset_does_not_touch_lesson_history(config, fake_web, model, fake_articles):
    run(config)
    pipeline.run(config, now=NOW + timedelta(days=1))
    assert lesson_rows(config) == [SCHEDULE[0].id, SCHEDULE[1].id]

    reset(config)
    pipeline.run(config, now=NOW + timedelta(days=1, minutes=10))  # same day: the saved lesson is reused
    pipeline.run(config, now=NOW + timedelta(days=2))

    assert lesson_rows(config) == [SCHEDULE[0].id, SCHEDULE[1].id, SCHEDULE[2].id]  # carried on, not restarted
    assert model.lesson_requests == [SCHEDULE[0].title, SCHEDULE[1].title, SCHEDULE[2].title]


def test_a_story_the_model_fails_on_after_a_reset_is_offered_again(config, fake_web, model, fake_articles):
    run(config)
    reset(config)
    model.failing_titles = {"Sparse attention"}

    titles, ok = run(config, minutes=10)
    assert not ok and titles == FIRST_THREE
    assert query(config, "SELECT COUNT(*) FROM repeat_showings") == [(2,)]  # only the two that were summarised

    model.failing_titles = set()
    model.selected = [1, 2, 3]
    again, ok = run(config, minutes=20)
    assert ok and "Sparse attention" in again and not {"Model X released", "Running LLMs on a laptop"} & set(again)


def test_runs_never_reset_story_memory_themselves(config, fake_web, model, fake_articles):
    for minutes in (0, 10, 20):
        run(config, minutes)

    assert query(config, "SELECT COUNT(*) FROM story_resets") == [(0,)]
    assert len(shown_titles(config)) == 6


# --- the command


@pytest.fixture
def in_data(config, monkeypatch, tmp_path):
    """Run the CLI with its default configuration, whose data directory is the fixture config's."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DAILYGRAD_CONFIG", raising=False)
    return config


@pytest.mark.parametrize("arguments", [[], ["--dry-run"]])
def test_without_confirm_the_command_previews_and_changes_nothing(in_data, fake_web, model, fake_articles, capsys, arguments):
    run(in_data)
    before = in_data.db_path.read_bytes()
    capsys.readouterr()

    assert cli.main(["reset-story-memory", *arguments]) == 0

    shown = capsys.readouterr().out
    assert "Stories remembered:  3" in shown and "Runs recorded:       1" in shown
    assert "Dry run: nothing was changed. To reset, run: dailygrad reset-story-memory --confirm" in shown
    assert in_data.db_path.read_bytes() == before  # not one byte
    assert run(in_data, minutes=10)[0] != FIRST_THREE  # and the stories are still held back


def test_confirm_performs_the_reset_once(in_data, fake_web, model, fake_articles, capsys):
    run(in_data)
    capsys.readouterr()

    assert cli.main(["reset-story-memory", "--confirm"]) == 0
    assert "Story memory reset: 3 stories may be shown again." in capsys.readouterr().out
    assert query(in_data, "SELECT after_run_id FROM story_resets") == [(1,)]
    assert table_count(in_data, "runs") == 1  # the command generates no digest

    assert cli.main(["reset-story-memory", "--confirm"]) == 0  # nothing left to free: no second reset row
    assert "there is nothing to reset" in capsys.readouterr().out
    assert query(in_data, "SELECT COUNT(*) FROM story_resets") == [(1,)]

    assert run(in_data, minutes=10)[0] == FIRST_THREE


def test_the_two_options_cannot_be_combined(in_data, capsys):
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["reset-story-memory", "--dry-run", "--confirm"])

    assert exit_info.value.code == 2 and not in_data.db_path.exists()


@pytest.mark.parametrize("arguments", [[], ["--confirm"]])
def test_without_a_database_the_command_creates_nothing(in_data, capsys, arguments):
    assert cli.main(["reset-story-memory", *arguments]) == 0

    assert "There is no database yet" in capsys.readouterr().out
    assert not in_data.db_path.exists() and not in_data.db_path.parent.exists()


def test_a_file_that_is_not_a_database_is_reported_and_left_alone(in_data, capsys):
    in_data.db_path.parent.mkdir(parents=True)
    in_data.db_path.write_bytes(b"this is not sqlite" * 100)

    assert cli.main(["reset-story-memory", "--confirm"]) == 1

    assert "cannot use the database" in capsys.readouterr().err
    assert in_data.db_path.read_bytes() == b"this is not sqlite" * 100
