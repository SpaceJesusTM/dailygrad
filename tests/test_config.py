from pathlib import Path

import pytest

from dailygrad.config import DEFAULT_FEEDS, Config, ConfigError, Feed, find_config_file, load_config


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch, tmp_path):
    monkeypatch.delenv("DAILYGRAD_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path)


def write(tmp_path, text):
    path = tmp_path / "custom.toml"
    path.write_text(text)
    return path


def test_defaults_without_a_config_file():
    config = load_config()

    assert config == Config()
    assert config.rss.feeds == DEFAULT_FEEDS
    assert str(config.db_path) == "data/dailygrad.db"
    assert str(config.digest_dir) == "data/digests"


def test_file_overrides_only_what_it_sets(tmp_path):
    path = write(
        tmp_path,
        """
        data_dir = "/var/lib/dailygrad"

        [filter]
        shortlist_size = 12

        [hackernews]
        enabled = false

        [[rss.feeds]]
        name = "My Lab"
        url = "https://lab.example/rss.xml"
        """,
    )

    config = load_config(path)

    assert str(config.db_path) == "/var/lib/dailygrad/dailygrad.db"
    assert config.filter.shortlist_size == 12
    assert config.filter.max_age_hours == 48
    assert config.hackernews.enabled is False
    assert config.rss.feeds == [Feed("My Lab", "https://lab.example/rss.xml")]


def test_config_found_via_environment_then_working_directory(tmp_path, monkeypatch):
    (tmp_path / "dailygrad.toml").write_text("[filter]\nshortlist_size = 11\n")
    assert load_config().filter.shortlist_size == 11

    monkeypatch.setenv("DAILYGRAD_CONFIG", str(write(tmp_path, "[filter]\nshortlist_size = 19\n")))
    assert load_config().filter.shortlist_size == 19


def test_story_count_and_ranking_defaults_and_overrides(tmp_path):
    defaults = Config()
    assert (defaults.final_story_count, defaults.filter.shortlist_size, defaults.hackernews.keyword_boost) == (5, 18, 4.0)
    assert str(defaults.latest_markdown_path) == "data/latest.md" and str(defaults.latest_json_path) == "data/latest.json"

    config = load_config(write(tmp_path, "final_story_count = 4\n[hackernews]\nkeyword_boost = 2\n"))

    assert (config.final_story_count, config.hackernews.keyword_boost) == (4, 2.0)


def test_find_config_file(tmp_path, monkeypatch):
    assert find_config_file() is None
    explicit = write(tmp_path, "")
    assert find_config_file(explicit) == explicit
    monkeypatch.setenv("DAILYGRAD_CONFIG", str(explicit))
    assert find_config_file() == explicit


def test_ollama_defaults_and_overrides(tmp_path):
    defaults = Config().ollama
    assert (defaults.url, defaults.model) == ("http://localhost:11434", "qwen3.5:4b-q4_K_M")
    assert (defaults.context_tokens, defaults.temperature, defaults.think) == (8192, 0.2, False)

    path = write(tmp_path, '[ollama]\nurl = "http://gpu-box:11434"\nmodel = "llama3.2:3b"\ntemperature = 0\n')
    ollama = load_config(path).ollama

    assert (ollama.url, ollama.model, ollama.temperature) == ("http://gpu-box:11434", "llama3.2:3b", 0.0)
    assert ollama.context_tokens == 8192


@pytest.mark.parametrize(
    "text, message",
    [
        ("[filter]\nshortlist = 5\n", "unknown setting: filter.shortlist"),
        ("[hackernews]\nmin_points = 'lots'\n", "hackernews.min_points must be of type int"),
        ("filter = 3\n", "filter must be a table"),
        ("final_story_count = 0\n", "final_story_count must be at least 1"),
        ("final_story_count = 6\n[filter]\nshortlist_size = 5\n", "shortlist_size must be at least final_story_count"),
        ("[hackernews]\nkeyword_boost = 0.5\n", "keyword_boost must be at least 1"),
        ("[ollama]\ntemperature = 'warm'\n", "ollama.temperature must be of type float"),
        ("[[rss.feeds]]\nname = 'No URL'\n", "needs exactly a name and a url"),
        ("not toml at all", "cannot read config file"),
    ],
)
def test_invalid_config_is_rejected(tmp_path, text, message):
    with pytest.raises(ConfigError, match=message):
        load_config(write(tmp_path, text))


def test_missing_config_file_is_an_error(tmp_path):
    with pytest.raises(ConfigError, match="cannot read config file"):
        load_config(tmp_path / "missing.toml")


def test_example_config_is_valid_and_matches_the_built_in_defaults():
    """config.example.toml documents the defaults, so the two must not drift apart."""
    example = Path(__file__).parent.parent / "config.example.toml"

    assert load_config(example) == Config()
