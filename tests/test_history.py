"""Run archives: every run's digest is kept, none is ever replaced, and nothing is made up."""

import json
import os
import sqlite3
from datetime import date, datetime, timezone

import pytest

from dailygrad import cli, db, history, output
from dailygrad.config import Config
from dailygrad.models import Lesson, Story, Topic

DAY = date(2026, 10, 8)
TOPIC = Topic("tf-masking", "architectures", "Transformers", 5, "Causal and padding masks", ("a", "b", "c"), "What does the causal mask do?")
SOURCES = [{"id": "hacker-news", "name": "Hacker News", "group": "community", "enabled": True}]


@pytest.fixture
def config(tmp_path):
    return Config(data_dir=str(tmp_path / "data"))


@pytest.fixture
def in_tmp(tmp_path, monkeypatch):
    """Run the CLI in an empty directory, so it uses the default data directory there."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DAILYGRAD_CONFIG", raising=False)
    return Config(data_dir=str(tmp_path / "data"))


def at(hour, day=DAY):
    return datetime(day.year, day.month, day.day, hour, 30, 15, tzinfo=timezone.utc)


def write_run(config, make_candidate, run_id, hour, title="A story", day=DAY, sources=SOURCES):
    """Write one run's outputs as the pipeline does. Returns (markdown, the document's JSON text)."""
    story = Story(make_candidate(title), f"{title} happened.", "It matters.", "article")
    document = output.digest_document(run_id, day, at(hour, day), "test-model", [story], [], Lesson(TOPIC, "A lesson."), sources)
    markdown = f"# DailyGrad — {day.isoformat()}\n\n### 1. [{title}]({story.candidate.url})\n"
    output.write_outputs(config, day, markdown, document)
    return markdown, json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def archive_files(config):
    return sorted(str(path.relative_to(config.run_archive_dir)) for path in config.run_archive_dir.rglob("*") if path.is_file())


# --- what a run writes


def test_a_run_is_archived_under_its_date_run_id_and_generation_time(config, make_candidate):
    markdown, json_text = write_run(config, make_candidate, 2, hour=12)

    assert archive_files(config) == ["2026-10-08/run-2-20261008T123015Z.json", "2026-10-08/run-2-20261008T123015Z.md"]
    archive = config.run_archive_dir / "2026-10-08" / "run-2-20261008T123015Z.json"
    assert archive.read_text(encoding="utf-8") == json_text  # the whole document: stories, lesson, recall, sources
    assert archive.read_bytes() == config.latest_json_path.read_bytes()  # byte for byte what latest.json held
    assert archive.with_suffix(".md").read_text(encoding="utf-8") == markdown


def test_same_day_runs_each_keep_their_own_archive(config, make_candidate):
    first = write_run(config, make_candidate, 2, hour=12, title="Morning story")
    disabled = [{**SOURCES[0], "enabled": False}]
    second = write_run(config, make_candidate, 3, hour=15, title="Afternoon story", sources=disabled)
    third = write_run(config, make_candidate, 4, hour=18, title="Evening story")

    runs = history.archived_runs(config)
    assert [(run["run_id"], run["date"]) for run in runs] == [(2, "2026-10-08"), (3, "2026-10-08"), (4, "2026-10-08")]
    for run, (markdown, json_text) in zip(runs, (first, second, third)):
        assert open(run["json"], encoding="utf-8").read() == json_text  # the earlier runs are exactly as written
        assert open(run["markdown"], encoding="utf-8").read() == markdown
    assert json.loads(open(runs[1]["json"], encoding="utf-8").read())["sources"] == disabled  # its own source settings
    # The existing outputs are unchanged: the dated files and latest.* hold the day's last run.
    assert json.loads((config.digest_dir / "2026-10-08.json").read_text(encoding="utf-8"))["run_id"] == 4
    assert config.latest_json_path.read_text(encoding="utf-8") == third[1]
    assert sorted(path.name for path in config.digest_dir.iterdir()) == ["2026-10-08.json", "2026-10-08.md", "runs"]


def test_an_archive_is_never_overwritten(config, make_candidate):
    _, json_text = write_run(config, make_candidate, 2, hour=12)
    archive = config.run_archive_dir / "2026-10-08" / "run-2-20261008T123015Z.json"

    assert history.archive_run(config, None, json_text) == []  # the same run again: nothing to do
    other = json_text.replace("A story happened.", "Something else happened.")
    with pytest.raises(history.HistoryError) as refused:
        history.archive_run(config, None, other)  # the same identity with other content

    assert refused.value.code == "archive_conflict"
    assert archive.read_text(encoding="utf-8") == json_text


def test_a_run_after_a_database_reset_does_not_collide_with_the_old_run_of_that_id(config, make_candidate):
    write_run(config, make_candidate, 1, hour=9, title="Before the reset")
    write_run(config, make_candidate, 1, hour=14, title="After the reset")

    runs = history.archived_runs(config)
    assert [(run["run_id"], run["generated_at"]) for run in runs] == [
        (1, "2026-10-08T09:30:15+00:00"), (1, "2026-10-08T14:30:15+00:00")
    ]  # fmt: skip
    with pytest.raises(history.HistoryError) as refused:
        history.find_run(config, 1)
    assert refused.value.code == "ambiguous_run"


def test_archives_are_written_completely_or_not_at_all(config, make_candidate, monkeypatch):
    write_run(config, make_candidate, 2, hour=12)
    before = archive_files(config)

    def failing_fsync(descriptor):
        raise OSError("disk full")

    monkeypatch.setattr(os, "fsync", failing_fsync)
    with pytest.raises(OSError, match="disk full"):
        write_run(config, make_candidate, 3, hour=15)

    assert archive_files(config) == before  # no partial archive and no temporary file


def test_a_run_whose_outputs_fail_leaves_no_archive(config, make_candidate, monkeypatch):
    write_run(config, make_candidate, 2, hour=12)
    before = archive_files(config)
    real_replace = os.replace

    def failing_replace(source, target):
        if str(target).endswith("latest.json"):
            raise OSError("cannot replace latest.json")
        real_replace(source, target)

    monkeypatch.setattr(os, "replace", failing_replace)
    with pytest.raises(OSError, match="cannot replace"):
        write_run(config, make_candidate, 3, hour=15)  # the pipeline rolls this run back

    assert archive_files(config) == before  # so no archive names it


def test_find_run_by_id_and_date(config, make_candidate):
    write_run(config, make_candidate, 2, hour=12)
    write_run(config, make_candidate, 5, hour=12, day=date(2026, 10, 9))

    assert history.find_run(config, 5)["date"] == "2026-10-09"
    assert history.find_run(config, 2, "2026-10-08")["generated_at"] == "2026-10-08T12:30:15+00:00"
    for run_id, day in ((7, None), (2, "2026-10-09")):
        with pytest.raises(history.HistoryError) as refused:
            history.find_run(config, run_id, day)
        assert refused.value.code == "not_found"


def test_files_that_are_not_what_their_name_says_are_not_listed(config, make_candidate):
    _, json_text = write_run(config, make_candidate, 2, hour=12)
    directory = config.run_archive_dir / "2026-10-08"
    (directory / "run-9-20261008T000000Z.json").write_text(json_text, encoding="utf-8")  # holds run 2
    (directory / "run-8-20261008T000000Z.json").write_text("{not json", encoding="utf-8")
    (directory / "notes.txt").write_text("not an archive", encoding="utf-8")

    assert [run["run_id"] for run in history.archived_runs(config)] == [2]


# --- digests written before archives existed


def write_legacy(config, run_id, hour, day=DAY, markdown=None):
    """The files a run left before archives existed: the dated pair and latest.*, and no archive."""
    document = output.digest_document(run_id, day, at(hour, day), "test-model", [], [], Lesson(TOPIC, "A lesson."), SOURCES)
    json_text = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
    markdown = markdown or f"# DailyGrad — {day.isoformat()}\n\n## AI News\n\nNo new stories today.\n"
    for path in (config.digest_dir / f"{day.isoformat()}.json", config.latest_json_path):
        output.write_atomic(path, json_text)
    for path in (config.digest_dir / f"{day.isoformat()}.md", config.latest_markdown_path):
        output.write_atomic(path, markdown)
    return json_text


def test_backfill_archives_the_digests_still_on_disk_and_only_those(config):
    older = write_legacy(config, 1, hour=9, day=date(2026, 10, 7))
    latest = write_legacy(config, 3, hour=15)  # run 2 was this day's first run: its files were replaced by run 3

    results = history.backfill(config)

    assert [(r["run_id"], r["outcome"], r["markdown"]) for r in results] == [(3, "archived", True), (1, "archived", True)]
    runs = history.archived_runs(config)
    assert [run["run_id"] for run in runs] == [1, 3]  # run 2 is gone, and nothing was invented for it
    assert open(runs[0]["json"], encoding="utf-8").read() == older
    assert open(runs[1]["json"], encoding="utf-8").read() == latest
    assert config.latest_json_path.read_text(encoding="utf-8") == latest  # the originals are untouched
    assert [r["outcome"] for r in history.backfill(config)] == ["already_archived", "already_archived"]  # safe to repeat


def test_backfill_does_not_pair_a_digest_with_another_runs_markdown(config):
    write_legacy(config, 3, hour=15, markdown="# DailyGrad — 2026-10-07\n\nYesterday's digest.\n")

    (result,) = history.backfill(config)

    assert (result["outcome"], result["markdown"]) == ("archived", False)
    assert archive_files(config) == ["2026-10-08/run-3-20261008T153015Z.json"]


def test_backfill_skips_files_that_are_not_digests(config):
    output.write_atomic(config.latest_json_path, "{not json")
    output.write_atomic(config.digest_dir / "2026-10-07.json", json.dumps({"run_id": 0, "date": "2026-10-07"}))

    results = history.backfill(config)

    assert [r["outcome"] for r in results] == ["skipped", "skipped"]
    assert all(r["reason"] for r in results) and not config.run_archive_dir.exists()


def test_the_next_run_archives_the_digest_it_is_about_to_replace(config, make_candidate):
    legacy = write_legacy(config, 2, hour=9)  # written before archives existed

    write_run(config, make_candidate, 3, hour=15)

    runs = history.archived_runs(config)
    assert [run["run_id"] for run in runs] == [2, 3]
    assert open(runs[0]["json"], encoding="utf-8").read() == legacy


def test_a_previous_digest_that_cannot_be_archived_does_not_stop_the_run(config, make_candidate):
    output.write_atomic(config.latest_json_path, "{not json")

    write_run(config, make_candidate, 3, hour=15)

    assert [run["run_id"] for run in history.archived_runs(config)] == [3]


# --- the database is only read


def record_runs(config, *runs):
    conn = db.connect(config.db_path)
    with conn:
        for run_id, day in runs:
            conn.execute("INSERT INTO runs (id, run_date, created_at, digest_path) VALUES (?, ?, ?, ?)",
                         (run_id, day, f"{day}T09:00:00+00:00", "x"))  # fmt: skip
    conn.close()


def test_runs_recorded_without_an_archive_are_reported_not_invented(config, make_candidate):
    record_runs(config, (1, "2026-10-07"), (2, "2026-10-08"), (3, "2026-10-08"))
    write_run(config, make_candidate, 3, hour=15)
    before = config.db_path.read_bytes()

    runs = history.archived_runs(config)
    missing = history.unarchived_runs(config, runs)

    assert [run["run_id"] for run in runs] == [3]
    assert [(run["run_id"], run["date"]) for run in missing] == [(1, "2026-10-07"), (2, "2026-10-08")]
    assert [run["run_id"] for run in history.unarchived_runs(config, runs, "2026-10-08")] == [2]
    assert config.db_path.read_bytes() == before  # the database is read, never written


def test_listing_without_a_database_creates_nothing(config):
    assert history.archived_runs(config) == [] and history.unarchived_runs(config, []) == []
    assert db.recorded_runs(config.db_path) == []
    assert not (config.db_path.parent).exists()


def test_recorded_runs_reads_a_database_with_no_runs_table(tmp_path):
    path = tmp_path / "empty.db"
    sqlite3.connect(path).close()

    assert db.recorded_runs(path) == []


# --- command line


def test_cli_history_lists_runs_as_a_table_and_as_json(in_tmp, make_candidate, capsys):
    record_runs(in_tmp, (2, "2026-10-08"), (3, "2026-10-08"))
    write_run(in_tmp, make_candidate, 3, hour=15)

    assert cli.main(["history"]) == 0
    table = capsys.readouterr().out
    assert "2026-10-08  3    2026-10-08T15:30:15+00:00  ok      1        yes" in table
    assert "not archived, so their digests are not available: 2 (2026-10-08)" in table

    assert cli.main(["history", "list", "--json", "--date", "2026-10-08"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is True and [run["run_id"] for run in result["runs"]] == [3]
    assert list(result["runs"][0]) == ["run_id", "date", "generated_at", "status", "story_count", "has_lesson", "json", "markdown"]
    assert result["not_archived"] == [{"run_id": 2, "date": "2026-10-08", "recorded_at": "2026-10-08T09:00:00+00:00"}]

    assert cli.main(["history", "--date", "2026-10-09", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"ok": True, "runs": [], "not_archived": []}


def test_cli_history_show_prints_the_archived_document_or_its_markdown(in_tmp, make_candidate, capsys):
    markdown, json_text = write_run(in_tmp, make_candidate, 2, hour=12, title="Morning story")
    write_run(in_tmp, make_candidate, 3, hour=15, title="Afternoon story")

    assert cli.main(["history", "show", "2"]) == 0
    assert capsys.readouterr().out == json_text  # the first run, after a second run that day
    assert cli.main(["history", "show", "2", "--markdown", "--date", "2026-10-08"]) == 0
    assert capsys.readouterr().out == markdown


@pytest.mark.parametrize(
    ("arguments", "code"),
    [
        (["show", "7"], "not_found"),
        (["list", "--date", "8 October", "--json"], "bad_date"),
        (["list", "--date", "2026-02-30", "--json"], "bad_date"),
    ],
)
def test_cli_history_refuses_with_exit_2_and_a_code(in_tmp, make_candidate, capsys, arguments, code):
    write_run(in_tmp, make_candidate, 2, hour=12)

    assert cli.main(["history", *arguments]) == 2
    captured = capsys.readouterr()
    assert captured.err.startswith("dailygrad: ")
    if "--json" in arguments:
        assert json.loads(captured.out)["error"]["code"] == code


def test_cli_history_backfill_reports_what_it_archived(in_tmp, capsys):
    write_legacy(in_tmp, 3, hour=15)

    assert cli.main(["history", "backfill"]) == 0
    assert capsys.readouterr().out == "archived  run 3 of 2026-10-08\n"
    assert cli.main(["history", "backfill", "--json"]) == 0
    (result,) = json.loads(capsys.readouterr().out)["results"]
    assert (result["outcome"], result["run_id"], result["markdown"]) == ("already_archived", 3, True)


def test_cli_history_backfill_with_nothing_to_archive(in_tmp, capsys):
    assert cli.main(["history", "backfill"]) == 0
    assert capsys.readouterr().out == "No digest files to archive.\n"
    assert not (in_tmp.db_path.parent).exists()  # and it created nothing
