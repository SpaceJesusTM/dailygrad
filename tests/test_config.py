import pytest

from dailygrad.config import DEFAULT_FEEDS, Config, ConfigError, Feed, load_config


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


@pytest.mark.parametrize(
    "text, message",
    [
        ("[filter]\nshortlist = 5\n", "unknown setting: filter.shortlist"),
        ("[hackernews]\nmin_points = 'lots'\n", "hackernews.min_points must be of type int"),
        ("filter = 3\n", "filter must be a table"),
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
