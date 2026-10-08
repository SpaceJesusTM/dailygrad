"""Source preferences: the registry, the preferences file, `dailygrad sources`, and their effect on a run."""

import json
import logging
import os
import sqlite3
import subprocess
import sys
import threading
from datetime import timedelta
from pathlib import Path

import pytest
import requests

from conftest import NOW
from dailygrad import articles, cli, db, llm, output, pipeline, preferences, stories
from dailygrad.config import Config, ConfigError, Feed
from dailygrad.sources import available_sources, hackernews, huggingface, source_id
from test_pipeline import ABSTRACT, FEED, HN_BODY, fake_articles, fake_web, hn_hit, model, read_latest  # noqa: F401 (fixtures)

NEW_IDS = ["anthropic-news", "meta-ai-research", "nvidia-developer-blog", "mistral-ai-news", "microsoft-research"]
LABS = ["openai", "google-deepmind", "google-research", *NEW_IDS]
ALL_IDS = [*LABS, "hugging-face-blog", "hugging-face-daily-papers", "hacker-news"]
ROOT = Path(__file__).parent.parent


@pytest.fixture
def config(tmp_path):
    return Config(data_dir=str(tmp_path / "data"))


def enabled(config):
    return [source["id"] for source in preferences.status(config)["sources"] if source["enabled"]]


def stored(config):
    return json.loads(config.source_preferences_path.read_text(encoding="utf-8"))


def refused(config, action, names):
    with pytest.raises(preferences.PreferencesError) as error:
        preferences.change(config, action, names)
    return error.value.code


# --- the registry


def test_registry_lists_the_built_in_sources_in_fetch_order_with_groups():
    sources = available_sources(Config())

    assert [source.id for source in sources] == ALL_IDS
    assert [source.name for source in sources][-2:] == ["Hugging Face Daily Papers", "Hacker News"]
    assert [source.group for source in sources] == ["labs"] * 8 + ["hugging-face", "hugging-face", "community"]


def test_source_ids_are_derived_from_names():
    assert source_id("Google DeepMind") == "google-deepmind"
    assert source_id("  My Lab's Blog! ") == "my-lab-s-blog"


def test_a_feed_added_in_the_config_gets_an_id_and_no_group():
    config = Config()
    config.rss.feeds = [Feed("My favourite lab", "https://lab.example/feed.xml")]
    config.huggingface.enabled = False

    assert [(s.id, s.group) for s in available_sources(config)] == [("my-favourite-lab", None), ("hacker-news", "community")]


@pytest.mark.parametrize("name", ["Hacker News", "OpenAI", "labs", "ALL", "!!!"])
def test_feed_names_that_cannot_be_told_apart_are_a_config_error(name):
    config = Config()
    config.rss.feeds.append(Feed(name, "https://other.example/feed.xml"))

    with pytest.raises(ConfigError):
        available_sources(config)


# --- defaults


def test_without_a_preferences_file_every_source_is_enabled_and_nothing_is_created(config):
    status = preferences.status(config)

    assert enabled(config) == ALL_IDS
    assert (status["ok"], status["changed"], status["mode"]) == (True, False, "all_except")
    assert status["preferences_file"] == str(config.source_preferences_path.resolve())
    assert preferences.disabled_for_run(config, available_sources(config)) == set()
    assert not Path(config.data_dir).exists()


def test_status_lists_the_groups_and_their_members(config):
    assert preferences.status(config)["groups"] == [
        {"id": "labs", "name": "AI labs and research", "sources": LABS},
        {"id": "hugging-face", "name": "Hugging Face", "sources": ["hugging-face-blog", "hugging-face-daily-papers"]},
        {"id": "community", "name": "Community", "sources": ["hacker-news"]},
    ]


# --- changes


def test_disable_and_enable_a_single_source(config):
    result = preferences.change(config, "disable", ["google-research"])

    assert result["changed"] and enabled(config) == [id for id in ALL_IDS if id != "google-research"]
    assert stored(config)["version"] == 1 and stored(config)["disabled"] == ["google-research"]

    assert preferences.change(config, "enable", ["Google-Research "])["changed"]  # case and spaces are forgiven
    assert enabled(config) == ALL_IDS and stored(config)["disabled"] == []


def test_disable_and_enable_a_group(config):
    preferences.change(config, "disable", ["hugging-face"])
    assert enabled(config) == [*LABS, "hacker-news"]

    preferences.change(config, "enable", ["hugging-face-daily-papers"])  # one member back on
    assert "hugging-face-daily-papers" in enabled(config) and "hugging-face-blog" not in enabled(config)

    preferences.change(config, "enable", ["hugging-face"])
    assert enabled(config) == ALL_IDS


def test_sources_and_groups_can_be_mixed_in_one_request(config):
    preferences.change(config, "disable", ["community", "openai"])

    assert enabled(config) == [*LABS[1:], "hugging-face-blog", "hugging-face-daily-papers"]


def test_set_replaces_the_enabled_selection(config):
    preferences.change(config, "disable", ["openai"])

    preferences.change(config, "set", ["labs", "hacker-news"])
    assert enabled(config) == [*LABS, "hacker-news"]

    preferences.change(config, "set", ["all"])
    assert enabled(config) == ALL_IDS


def test_changes_are_idempotent_and_do_not_rewrite_the_file(config):
    preferences.change(config, "disable", ["hacker-news"])
    path = config.source_preferences_path
    before = (path.read_bytes(), path.stat().st_mtime_ns)

    assert preferences.change(config, "disable", ["hacker-news", "community"])["changed"] is False
    assert preferences.change(config, "enable", ["openai"])["changed"] is False
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


def test_unknown_ids_are_rejected_and_nothing_is_changed(config):
    preferences.change(config, "disable", ["openai"])

    for action in preferences.ACTIONS:
        assert refused(config, action, ["hacker-news", "anthropic"]) == "unknown_source"
    assert refused(config, "disable", ["../../etc/passwd"]) == "unknown_source"
    assert stored(config)["disabled"] == ["openai"]


def test_error_for_an_unknown_id_names_it_and_the_known_ones(config):
    with pytest.raises(preferences.PreferencesError, match="unknown source or group: anthropic .*hacker-news.*labs.*all"):
        preferences.change(config, "enable", ["anthropic"])


def test_disabling_every_source_is_rejected(config):
    assert refused(config, "disable", ["all"]) == "no_sources_enabled"
    assert not config.source_preferences_path.exists()

    preferences.change(config, "set", ["hacker-news"])
    assert refused(config, "disable", ["community"]) == "no_sources_enabled"  # the last one left
    assert refused(config, "disable", ["hacker-news"]) == "no_sources_enabled"
    assert enabled(config) == ["hacker-news"]


def test_an_unsupported_action_is_a_programming_error(config):
    with pytest.raises(ValueError):
        preferences.change(config, "delete", ["openai"])


# --- persistence


def test_preferences_persist_for_a_fresh_config_object(config):
    preferences.change(config, "disable", ["hugging-face"])

    again = Config(data_dir=config.data_dir)
    assert enabled(again) == [*LABS, "hacker-news"]
    assert preferences.disabled_for_run(again, available_sources(again)) == {"hugging-face-blog", "hugging-face-daily-papers"}


def run_cli(tmp_path, *arguments):
    environment = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    environment.pop("DAILYGRAD_CONFIG", None)
    return subprocess.run(
        [sys.executable, "-m", "dailygrad.cli", "sources", *arguments, "--json"],
        cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=60,
    )  # fmt: skip


def test_preferences_persist_across_separate_processes(tmp_path):
    first = run_cli(tmp_path, "disable", "hugging-face")
    second = run_cli(tmp_path, "list")
    refusal = run_cli(tmp_path, "disable", "all")

    assert first.returncode == 0 and json.loads(first.stdout)["changed"] is True
    assert second.returncode == 0
    assert [s["id"] for s in json.loads(second.stdout)["sources"] if not s["enabled"]] == ["hugging-face-blog", "hugging-face-daily-papers"]
    assert refusal.returncode == 2 and json.loads(refusal.stdout)["error"]["code"] == "no_sources_enabled"


def test_preferences_are_runtime_data_that_git_ignores():
    """They live in the data directory, which is ignored, so `git pull` cannot overwrite them."""
    assert Config().source_preferences_path == Path("data") / "source_preferences.json"
    assert "data/" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()


def test_by_default_a_source_added_later_is_enabled(config):
    """With no file, or after enable/disable alone, the file lists what is off, so anything new is on."""
    preferences.change(config, "disable", ["hacker-news"])
    assert list(stored(config)) == ["version", "disabled", "updated_at"]

    config.rss.feeds.append(Feed("Brand New Lab", "https://new.example/feed.xml"))  # as if an update added a source

    assert preferences.status(config)["mode"] == "all_except"
    assert "brand-new-lab" in enabled(config) and "hacker-news" not in enabled(config)


def test_an_explicit_selection_stays_exclusive_when_a_source_is_added_later(config):
    preferences.change(config, "set", ["labs", "hacker-news"])
    assert stored(config)["enabled_only"] == [*LABS, "hacker-news"]
    assert "disabled" not in stored(config)

    config.rss.feeds.append(Feed("Brand New Lab", "https://new.example/feed.xml"))

    assert preferences.status(config)["mode"] == "only"
    assert enabled(config) == [*LABS, "hacker-news"]
    assert "brand-new-lab" in preferences.disabled_for_run(config, available_sources(config))


def test_enable_and_disable_keep_an_explicit_selection_exclusive(config):
    preferences.change(config, "set", ["labs"])
    preferences.change(config, "enable", ["hacker-news"])
    preferences.change(config, "disable", ["google-research"])
    assert stored(config)["enabled_only"] == ["openai", "google-deepmind", *NEW_IDS, "hacker-news"]

    config.rss.feeds.append(Feed("Brand New Lab", "https://new.example/feed.xml"))
    assert "brand-new-lab" not in enabled(config)

    preferences.change(config, "enable", ["brand-new-lab"])  # a new source is switched on by asking for it
    assert "brand-new-lab" in enabled(config) and preferences.status(config)["mode"] == "only"


def test_even_a_selection_naming_every_source_is_exclusive(config):
    preferences.change(config, "set", ["labs", "hugging-face", "community"])
    assert enabled(config) == ALL_IDS and preferences.status(config)["mode"] == "only"

    config.rss.feeds.append(Feed("Brand New Lab", "https://new.example/feed.xml"))
    assert "brand-new-lab" not in enabled(config)

    assert preferences.change(config, "enable", ["all"])["mode"] == "only"  # enable never changes the mode
    assert "brand-new-lab" in enabled(config)


def test_set_all_returns_to_the_default_where_new_sources_are_enabled(config):
    preferences.change(config, "set", ["labs"])

    result = preferences.change(config, "set", ["all"])
    assert result["changed"] and result["mode"] == "all_except" and stored(config)["disabled"] == []

    config.rss.feeds.append(Feed("Brand New Lab", "https://new.example/feed.xml"))
    assert "brand-new-lab" in enabled(config)

    assert preferences.change(config, "set", ["all", "openai"])["mode"] == "all_except"  # `all` anywhere means all


def test_ids_that_no_longer_exist_are_ignored_and_dropped_by_the_next_change(config):
    path = config.source_preferences_path
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"version": 1, "enabled_only": ["hacker-news", "retired-source"], "note": "extra key"}))

    assert enabled(config) == ["hacker-news"]

    preferences.change(config, "enable", ["openai"])
    assert stored(config)["enabled_only"] == ["openai", "hacker-news"]


# --- malformed files


MALFORMED = [
    b"",
    b"{not json",
    b"[]",
    b'"text"',
    b"{}",
    b'{"version": 1}',
    b'{"disabled": []}',  # no version
    b'{"version": 2, "disabled": []}',  # a layout this version does not know
    b'{"version": 1, "disabled": "openai"}',
    b'{"version": 1, "disabled": [1]}',
    b'{"version": 1, "disabled": [], "enabled_only": ["openai"]}',  # which list applies?
    b"\xff\xfe",
]


@pytest.fixture(params=MALFORMED)
def broken(request, config):
    path = config.source_preferences_path
    path.parent.mkdir(parents=True)
    path.write_bytes(request.param)
    return request.param


def test_a_malformed_file_is_an_error_not_a_reason_to_enable_everything(config, broken):
    with pytest.raises(preferences.PreferencesError, match="sources set all") as error:
        preferences.disabled_for_run(config, available_sources(config))
    assert error.value.code == "invalid_preferences" and str(config.source_preferences_path) in str(error.value)

    with pytest.raises(preferences.PreferencesError):
        preferences.status(config)
    assert refused(config, "disable", ["openai"]) == "invalid_preferences"  # no guessing at the old state
    assert refused(config, "enable", ["openai"]) == "invalid_preferences"
    assert refused(config, "set", ["anthropic"]) == "unknown_source"
    assert config.source_preferences_path.read_bytes() == broken  # every refusal left the file alone


@pytest.mark.parametrize("selection, expected", [(["all"], ALL_IDS), (["labs"], LABS)])
def test_set_replaces_a_malformed_file(config, broken, selection, expected):
    assert preferences.change(config, "set", selection)["changed"]

    assert enabled(config) == expected
    assert preferences.disabled_for_run(config, available_sources(config)) == set(ALL_IDS) - set(expected)


def test_an_unreadable_file_is_also_an_error(config):
    config.source_preferences_path.mkdir(parents=True)  # a directory where the file should be

    with pytest.raises(preferences.PreferencesError, match="cannot read"):
        preferences.status(config)


# --- atomic writes and concurrent access


def test_a_failed_write_keeps_the_old_preferences(config, monkeypatch):
    preferences.change(config, "disable", ["openai"])
    before = config.source_preferences_path.read_bytes()

    def failing_replace(source, target):
        raise OSError("disk full")

    monkeypatch.setattr(output.os, "replace", failing_replace)
    with pytest.raises(OSError):
        preferences.change(config, "disable", ["hacker-news"])

    assert config.source_preferences_path.read_bytes() == before
    assert sorted(path.name for path in Path(config.data_dir).iterdir()) == [".source_preferences.json.lock", "source_preferences.json"]


def test_concurrent_changes_are_all_kept(config):
    config.rss.feeds = [Feed(f"Feed {n}", f"https://feed{n}.example/rss") for n in range(12)]
    errors = []

    def disable(name):
        try:
            preferences.change(config, "disable", [name])
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=disable, args=(f"feed-{n}",)) for n in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert stored(config)["disabled"] == [f"feed-{n}" for n in range(12)]  # no update overwrote another


def test_readers_always_see_a_complete_file_while_it_is_being_changed(config):
    preferences.change(config, "disable", ["openai"])
    problems, done = [], threading.Event()

    def read():
        while not done.is_set():
            try:
                preferences.read(config.source_preferences_path)
            except Exception as exc:
                problems.append(exc)

    reader = threading.Thread(target=read)
    reader.start()
    for number in range(60):
        preferences.change(config, "disable" if number % 2 else "enable", ["hacker-news"])
    done.set()
    reader.join()

    assert problems == []


# --- the command line


@pytest.fixture
def in_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DAILYGRAD_CONFIG", raising=False)
    return tmp_path


def test_cli_lists_sources_as_text(in_tmp, capsys):
    assert cli.main(["sources"]) == 0
    default_listing = capsys.readouterr().out
    assert cli.main(["sources", "list"]) == 0
    assert capsys.readouterr().out == default_listing

    lines = default_listing.splitlines()
    assert lines[-1] == "Selection: every source except those disabled above. A source added later is enabled."
    assert lines[0].split() == ["ID", "Source", "Group", "Status"]
    assert lines[1].split() == ["openai", "OpenAI", "labs", "enabled"]
    assert lines[4].split() == ["anthropic-news", "Anthropic", "News", "labs", "enabled"]
    assert lines[11].split() == ["hacker-news", "Hacker", "News", "community", "enabled"]
    assert "Groups: labs (AI labs and research), hugging-face (Hugging Face), community (Community), all" in lines
    assert f"Preferences file: {(in_tmp / 'data' / 'source_preferences.json').resolve()}" in lines
    assert not (in_tmp / "data").exists()  # listing creates nothing


def test_cli_lists_sources_as_json(in_tmp, capsys):
    cli.main(["sources", "disable", "community"])
    capsys.readouterr()

    assert cli.main(["sources", "list", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)

    assert list(result) == ["ok", "changed", "mode", "sources", "groups", "preferences_file"]
    assert [list(source) for source in result["sources"]] == [["id", "name", "group", "enabled"]] * 11
    assert result["sources"][-1] == {"id": "hacker-news", "name": "Hacker News", "group": "community", "enabled": False}
    assert [group["id"] for group in result["groups"]] == ["labs", "hugging-face", "community"]


def test_cli_changes_report_what_happened(in_tmp, capsys):
    assert cli.main(["sources", "disable", "hugging-face"]) == 0
    first = capsys.readouterr().out
    assert cli.main(["sources", "disable", "hugging-face"]) == 0
    second = capsys.readouterr().out

    assert "hugging-face-blog          Hugging Face Blog          hugging-face  disabled" in first
    assert first.endswith("Saved. The change applies from the next run; today's digest is not regenerated.\n")
    assert second.endswith("Nothing to change.\n")
    cli.main(["sources", "set", "labs"])
    assert "Selection: only the sources enabled above. A source added later stays disabled." in capsys.readouterr().out
    assert not (in_tmp / "data" / "latest.json").exists()  # changing sources never runs a digest


def test_cli_json_option_works_before_or_after_the_action(in_tmp, capsys):
    assert cli.main(["sources", "--json", "set", "labs", "hacker-news"]) == 0
    before = json.loads(capsys.readouterr().out)
    assert cli.main(["sources", "enable", "hugging-face", "--json"]) == 0
    after = json.loads(capsys.readouterr().out)

    assert before["changed"] and [s["id"] for s in before["sources"] if not s["enabled"]] == ["hugging-face-blog", "hugging-face-daily-papers"]
    assert after["changed"] and all(source["enabled"] for source in after["sources"])


@pytest.mark.parametrize(
    "arguments, code",
    [(["enable", "anthropic"], "unknown_source"), (["disable", "all"], "no_sources_enabled"), (["set", "nothing"], "unknown_source")],
)
def test_cli_refusals_exit_2_with_a_structured_error(in_tmp, capsys, arguments, code):
    assert cli.main(["sources", *arguments, "--json"]) == 2

    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert result["ok"] is False and result["error"]["code"] == code and result["error"]["message"]
    assert captured.err.startswith("dailygrad: ")
    assert not (in_tmp / "data" / "source_preferences.json").exists()


def test_cli_refusal_as_text_goes_to_stderr_only(in_tmp, capsys):
    assert cli.main(["sources", "disable", "all"]) == 2

    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == "dailygrad: at least one source must stay enabled\n"


def test_cli_reports_a_write_failure(in_tmp, capsys, monkeypatch):
    def failing_replace(source, target):
        raise OSError("disk full")

    monkeypatch.setattr(output.os, "replace", failing_replace)

    assert cli.main(["sources", "disable", "openai", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "write_failed"


def test_cli_reports_a_config_error_as_json(in_tmp, capsys):
    assert cli.main(["sources", "--json", "--config", "missing.toml"]) == 2
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "invalid_config"


def test_cli_needs_at_least_one_id_and_a_known_action(in_tmp, capsys):
    for arguments in (["sources", "disable"], ["sources", "delete", "openai"]):
        with pytest.raises(SystemExit) as exit_info:
            cli.main(arguments)
        assert exit_info.value.code == 2


def test_cli_config_shows_the_enabled_sources_and_the_preferences_file(in_tmp, capsys):
    cli.main(["sources", "set", "labs"])
    capsys.readouterr()

    assert cli.main(["config"]) == 0
    shown = capsys.readouterr().out
    assert "Sources:            OpenAI, Google DeepMind, Google Research, Anthropic News, Meta AI Research, " in shown
    assert "Mistral AI News, Microsoft Research\n" in shown
    assert f"Source preferences: {(in_tmp / 'data' / 'source_preferences.json').resolve()}" in shown


# --- effect on a run


@pytest.fixture
def run_config(tmp_path):
    """The three-source setup of test_pipeline: one feed, Hugging Face papers and Hacker News."""
    config = Config(data_dir=str(tmp_path / "data"))
    config.rss.feeds = [FEED]
    return config


def test_a_disabled_source_is_not_fetched(run_config, fake_web, model, fake_articles):
    preferences.change(run_config, "disable", ["hacker-news", "lab-blog"])
    del fake_web[hackernews.API_URL], fake_web[FEED.url]  # fetching either would raise KeyError and be reported

    digest, model_ok = pipeline.run(run_config, now=NOW)

    document = read_latest(run_config)
    assert model_ok and document["failed_sources"] == []
    assert {story["source"] for story in document["stories"]} == {"Hugging Face Daily Papers"}
    assert "Sources unavailable" not in digest


def test_digest_json_records_which_sources_the_run_used(run_config, fake_web, model, fake_articles):
    preferences.change(run_config, "disable", ["hugging-face"])

    pipeline.run(run_config, now=NOW)

    assert read_latest(run_config)["sources"] == [
        {"id": "lab-blog", "name": "Lab Blog", "group": None, "enabled": True},
        {"id": "hugging-face-daily-papers", "name": "Hugging Face Daily Papers", "group": "hugging-face", "enabled": False},
        {"id": "hacker-news", "name": "Hacker News", "group": "community", "enabled": True},
    ]


def test_a_hacker_news_link_to_a_disabled_publisher_is_still_shown(run_config, fake_web, model, fake_articles):
    """Disabling a feed stops fetching that feed. It does not filter the publisher out of other sources."""
    preferences.change(run_config, "set", ["hacker-news"])
    run_config.final_story_count = 4

    pipeline.run(run_config, now=NOW)

    stories = read_latest(run_config)["stories"]
    assert {story["source"] for story in stories} == {"Hacker News"}
    assert "lab.example/model-x" in [story["id"] for story in stories]


def test_a_small_pool_gives_a_shorter_digest_without_invented_stories(run_config, fake_web, model, fake_articles):
    preferences.change(run_config, "set", ["hugging-face-daily-papers"])  # two papers; the digest wants five

    digest, model_ok = pipeline.run(run_config, now=NOW)

    document = read_latest(run_config)
    assert model_ok and document["status"] == "ok"
    assert [story["title"] for story in document["stories"]] == ["Sparse attention", "Dense attention"]
    assert digest.count("### ") == 2 and document["lesson"] is not None


def test_a_change_applies_to_the_next_run_and_leaves_the_written_digest_alone(run_config, fake_web, model, fake_articles):
    pipeline.run(run_config, now=NOW)
    written = run_config.latest_json_path.read_bytes()

    preferences.change(run_config, "disable", ["hacker-news"])
    assert run_config.latest_json_path.read_bytes() == written

    pipeline.run(run_config, now=NOW)
    assert [source["enabled"] for source in read_latest(run_config)["sources"]] == [True, True, False]


def test_a_run_reads_the_preferences_once(run_config, fake_web, model, fake_articles, monkeypatch):
    preferences.change(run_config, "disable", ["hacker-news"])
    reads = []
    real_read = preferences.read

    def counting_read(path):
        reads.append(path)
        return real_read(path)

    monkeypatch.setattr(preferences, "read", counting_read)
    pipeline.run(run_config, now=NOW)

    assert len(reads) == 1


def test_a_run_with_a_malformed_file_stops_before_fetching_or_writing(run_config, fake_web, model, fake_articles):
    pipeline.run(run_config, now=NOW)
    written = run_config.latest_json_path.read_bytes()
    run_config.source_preferences_path.write_text("{broken")
    fake_web.clear()  # any fetch would now raise KeyError

    with pytest.raises(preferences.PreferencesError):
        pipeline.run(run_config, now=NOW)

    assert run_config.source_preferences_path.read_text() == "{broken"
    assert run_config.latest_json_path.read_bytes() == written  # the earlier digest is untouched
    assert model.unloads == 1  # only the first run reached the model


def test_cli_run_with_a_malformed_file_exits_2_and_recovers_after_set_all(
    in_tmp, fake_web, model, fake_articles, capsys, monkeypatch
):
    (in_tmp / "data").mkdir()
    (in_tmp / "data" / "source_preferences.json").write_text('{"version": 1, "disabled": "hacker-news"}')
    live = dict(fake_web)
    fake_web.clear()

    assert cli.main(["run"]) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and "is not a valid source preferences file" in captured.err
    assert "dailygrad sources set all" in captured.err
    assert not (in_tmp / "data" / "latest.json").exists() and not (in_tmp / "data" / "dailygrad.db").exists()

    assert cli.main(["sources", "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "invalid_preferences"
    assert cli.main(["config"]) == 0
    assert "Sources:            unknown: " in capsys.readouterr().out

    assert cli.main(["sources", "set", "all"]) == 0
    fake_web.update({hackernews.API_URL: live[hackernews.API_URL], huggingface.API_URL: []})
    for feed in Config().rss.feeds:
        fake_web[feed.url] = live[FEED.url]
    monkeypatch.setattr(articles, "download", lambda url, content_types: live[FEED.url])  # the Anthropic feed
    capsys.readouterr()
    assert cli.main(["run"]) == 0
    assert all(source["enabled"] for source in read_latest(Config())["sources"])


def test_a_run_keeps_history_and_older_digests(run_config, fake_web, model, fake_articles):
    pipeline.run(run_config, now=NOW)
    first_day = (run_config.digest_dir / f"{NOW.astimezone().date()}.json").read_bytes()

    preferences.change(run_config, "disable", ["hugging-face"])
    pipeline.run(run_config, now=NOW.replace(day=NOW.day + 1))

    assert (run_config.digest_dir / f"{NOW.astimezone().date()}.json").read_bytes() == first_day
    assert read_latest(run_config)["run_id"] == 2  # the same database carried on


def test_the_sources_key_is_an_addition_that_leaves_the_earlier_layout_intact(run_config, fake_web, model, fake_articles):
    """A consumer written before the key existed finds every key it used, in the same order, in schema version 1."""
    earlier = ["schema_version", "run_id", "date", "generated_at", "status", "model", "stories", "failed_sources", "lesson", "recall"]

    pipeline.run(run_config, now=NOW)

    document = read_latest(run_config)
    assert document["schema_version"] == 1
    assert [key for key in document if key != "sources"] == earlier
    assert all(type(name) is str for name in document["failed_sources"])  # still names, as before


# --- the feeds added after the first release


@pytest.mark.parametrize("id", NEW_IDS)
def test_each_new_feed_can_be_disabled_enabled_and_set_on_its_own(config, id):
    preferences.change(config, "disable", [id])
    assert enabled(config) == [other for other in ALL_IDS if other != id]

    preferences.change(config, "enable", [id])
    assert enabled(config) == ALL_IDS

    preferences.change(config, "set", [id])
    assert enabled(config) == [id] and stored(config)["enabled_only"] == [id]


def test_a_preferences_file_written_before_the_new_feeds_keeps_its_meaning(config):
    """An update must not rewrite or reinterpret a saved selection: only the documented rule for new sources applies."""
    path = config.source_preferences_path
    path.parent.mkdir(parents=True)

    earlier = '{"version": 1, "disabled": ["google-research", "hacker-news"], "updated_at": "2026-10-01T08:00:00+00:00"}'
    path.write_text(earlier)
    assert enabled(config) == [id for id in ALL_IDS if id not in ("google-research", "hacker-news")]  # new feeds on

    exclusive = '{"version": 1, "enabled_only": ["openai", "hacker-news"], "updated_at": "2026-10-01T08:00:00+00:00"}'
    path.write_text(exclusive)
    assert enabled(config) == ["openai", "hacker-news"]  # new feeds off until asked for
    assert path.read_text() == exclusive  # reading never rewrites the file

    preferences.change(config, "enable", ["mistral-ai-news"])
    assert enabled(config) == ["openai", "mistral-ai-news", "hacker-news"]


def feed_body(*items):
    """An RSS document of (title, link, age in hours) items."""
    entries = "".join(
        f"<item><title>{title}</title><link>{link}</link>"
        f"<pubDate>{(NOW - timedelta(hours=age)).strftime('%a, %d %b %Y %H:%M:%S GMT')}</pubDate></item>"
        for title, link, age in items
    )
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>Feed</title>{entries}</channel></rss>'.encode()


def test_a_run_with_every_built_in_source_still_gives_five_stories(tmp_path, fake_web, model, fake_articles, monkeypatch):
    """Eleven sources, one down, one malformed: five stories, fresh and deduplicated, and the rest of the run intact."""
    config = Config(data_dir=str(tmp_path / "data"))
    for feed in config.rss.feeds:
        slug = source_id(feed.name)
        fake_web[feed.url] = feed_body(
            (f"{feed.name} post", f"https://{slug}.example/new", 2),
            (f"{feed.name} old post", f"https://{slug}.example/old", 72),  # past the 48-hour limit
        )
    fake_web["https://mistral.ai/news/rss"] = b"<html><body>502 Bad Gateway"
    fake_web["https://openai.com/news/rss.xml"] = feed_body(("Model X released", "https://lab.example/model-x", 2))  # also on HN

    def download(url, content_types):  # the Anthropic feed's host is unreachable
        raise requests.ConnectionError("network down")

    monkeypatch.setattr(articles, "download", download)
    model.selected = [1, 2, 3, 4, 5]

    digest, model_ok = pipeline.run(config, now=NOW)

    document = read_latest(config)
    assert model_ok and document["status"] == "ok"
    assert len(document["stories"]) == 5 == config.final_story_count
    assert document["failed_sources"] == ["Anthropic News", "Mistral AI News"]
    assert "_Sources unavailable this run: Anthropic News, Mistral AI News._" in digest
    assert [source["id"] for source in document["sources"]] == ALL_IDS
    assert all(source["enabled"] for source in document["sources"])

    conn = sqlite3.connect(config.db_path)
    seen = [title for (title,) in conn.execute("SELECT title FROM items")]
    conn.close()
    assert not any("old post" in title for title in seen)  # the freshness filter applies to the new feeds
    assert seen.count("Model X released") == 1  # the feed entry and the Hacker News link are one story


# --- the shortlist the model chooses from


def test_the_model_chooses_five_from_at_most_25_balanced_candidates(tmp_path, fake_web, model, fake_articles, monkeypatch):
    """Every source has more than its share. Preferences and a story-memory reset work on top of the allocation."""
    config = Config(data_dir=str(tmp_path / "data"))
    for feed in config.rss.feeds:
        slug = source_id(feed.name)
        fake_web[feed.url] = feed_body(*[(f"{feed.name} post {n}", f"https://{slug}.example/{n}", n + 1) for n in range(6)])
    monkeypatch.setattr(articles, "download", lambda url, content_types: fake_web[url])  # the Anthropic feed
    fake_web[huggingface.API_URL] = [
        {"paper": {"id": f"2610.{n:05}", "title": f"Paper {n}", "upvotes": 10 + n, "summary": ABSTRACT,
                   "submittedOnDailyAt": "2026-10-07T00:00:00.000Z"}}
        for n in range(10)
    ]  # fmt: skip
    fake_web[hackernews.API_URL] = {"hits": [hn_hit(n, f"LLM story {n}", f"https://hn.example/{n}", 100 + n) for n in range(12)]}

    offered = []

    def chat_json(ollama, system, prompt, schema, temperature=None):
        if schema is stories.SELECTION_SCHEMA:
            offered.append([line for line in prompt.splitlines() if line[:1].isdigit()])
        return model.chat_json(ollama, system, prompt, schema, temperature)

    monkeypatch.setattr(llm, "chat_json", chat_json)
    model.selected = [25, 1, 2, 3, 4]

    def count(lines, text):
        return sum(text in line for line in lines)

    pipeline.run(config, now=NOW)

    (candidates,) = offered
    assert len(candidates) == 25
    assert (count(candidates, "(Hugging Face Daily Papers, "), count(candidates, "(Hacker News, ")) == (4, 6)
    assert all(count(candidates, f"({feed.name})") <= 3 for feed in config.rss.feeds)
    assert count(candidates, "(NVIDIA Developer Blog)") == 2  # nine feeds, fifteen places: one each, then the six newest
    document = read_latest(config)
    assert len(document["stories"]) == 5 and document["status"] == "ok"
    first_titles = [story["title"] for story in document["stories"]]

    # A disabled feed gives up its places; they go to other feeds, never beyond the feed limit.
    preferences.change(config, "disable", ["nvidia-developer-blog", "hacker-news"])
    pipeline.run(config, now=NOW)
    candidates = offered[-1]
    assert count(candidates, "(NVIDIA Developer Blog)") == 0 and count(candidates, "(Hacker News, ") == 0
    assert len(candidates) == 19 and count(candidates, "(Hugging Face Daily Papers, ") == 4
    assert not any(title in line for title in first_titles for line in candidates)  # shown stories are not offered again

    # After a story-memory reset the first run's stories are eligible again, under the same limits.
    preferences.change(config, "set", ["all"])
    conn = db.connect(config.db_path)
    with conn:
        db.reset_story_memory(conn, NOW)
    conn.close()
    pipeline.run(config, now=NOW)
    assert len(offered[-1]) == 25 and offered[-1] == offered[0]
