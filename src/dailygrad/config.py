"""Configuration: built-in defaults, optionally overridden by a TOML file."""

import os
import tomllib
from dataclasses import dataclass, field, is_dataclass
from pathlib import Path

DEFAULT_CONFIG_FILE = "dailygrad.toml"
CONFIG_ENV_VAR = "DAILYGRAD_CONFIG"

# Matched as whole words (plural allowed) against Hacker News titles, to rank AI stories higher.
DEFAULT_KEYWORDS = [
    "AI", "AGI", "LLM", "GPT", "machine learning", "deep learning", "neural",
    "transformer", "diffusion", "language model", "foundation model",
    "fine-tuning", "embedding", "RAG", "agent", "agentic", "reinforcement learning",
    "OpenAI", "Anthropic", "DeepMind", "Claude", "Gemini", "Llama", "Mistral",
    "Qwen", "DeepSeek", "Hugging Face", "Ollama", "PyTorch", "MCP",
]  # fmt: skip

# The LeetCode tracks a rotation may name. The catalog (leetcode.toml) says which problems are in each.
LEETCODE_TRACKS = ("neetcode-150", "amd", "vanguard")


class ConfigError(ValueError):
    pass


@dataclass
class Feed:
    name: str
    url: str
    # For a feed published by someone other than the site it covers: an entry is kept only
    # if its link is https and on one of these hosts. Empty means any link is accepted.
    link_hosts: list[str] = field(default_factory=list)


DEFAULT_FEEDS = [
    Feed("OpenAI", "https://openai.com/news/rss.xml"),
    Feed("Google DeepMind", "https://deepmind.google/blog/rss.xml"),
    Feed("Google Research", "https://research.google/blog/rss/"),
    # Anthropic publishes no feed. This one is community-maintained, hence link_hosts.
    Feed(
        "Anthropic News",
        "https://raw.githubusercontent.com/taobojlen/anthropic-rss-feed/main/anthropic_news_rss.xml",
        link_hosts=["anthropic.com", "www.anthropic.com"],
    ),
    Feed("Meta AI Research", "https://engineering.fb.com/category/ai-research/feed/"),
    Feed("NVIDIA Developer Blog", "https://developer.nvidia.com/blog/feed/"),
    Feed("Mistral AI News", "https://mistral.ai/news/rss"),
    Feed("Microsoft Research", "https://www.microsoft.com/en-us/research/feed/"),
    Feed("Hugging Face Blog", "https://huggingface.co/blog/feed.xml"),
]


@dataclass
class FilterConfig:
    max_age_hours: int = 48
    shortlist_size: int = 25  # overall limit; the per-source max_candidates below add up to it
    keywords: list[str] = field(default_factory=lambda: list(DEFAULT_KEYWORDS))


@dataclass
class HackerNewsConfig:
    enabled: bool = True
    min_points: int = 50
    max_candidates: int = 6  # places in the shortlist, at most
    keyword_boost: float = 4.0  # a title matching a keyword ranks as if it were this many times as popular


@dataclass
class HuggingFaceConfig:
    enabled: bool = True
    min_upvotes: int = 5
    max_candidates: int = 4  # places in the shortlist, at most


@dataclass
class RssConfig:
    feeds: list[Feed] = field(default_factory=lambda: list(DEFAULT_FEEDS))
    max_candidates: int = 15  # places in the shortlist for all feeds together, at most
    max_per_feed: int = 3  # of which one feed may take this many


@dataclass
class OllamaConfig:
    url: str = "http://localhost:11434"
    model: str = "qwen3.5:4b-q4_K_M"
    context_tokens: int = 8192
    temperature: float = 0.2
    think: bool = False
    timeout_seconds: int = 180  # per model request; the first one includes loading the model


@dataclass
class LeetCodeConfig:
    enabled: bool = True
    # One track per exercise, repeating. A track may be left out or listed more than once.
    rotation: list[str] = field(default_factory=lambda: list(LEETCODE_TRACKS))
    model_hints: bool = True  # the model words the digest's hint; false prints the catalog's hint as written
    feedback_budget_seconds: int = 120  # for one `dailygrad leetcode answer` or `review`
    # How long the model stays loaded after an interactive reply, so a follow-up is quick. 0 unloads at once.
    keep_alive_seconds: int = 300


@dataclass
class Config:
    data_dir: str = "data"  # relative paths resolve against the working directory
    final_story_count: int = 5  # stories in the digest, when that many candidates are available
    # Seconds from the start of a run during which model requests may be made or retried.
    run_budget_seconds: int = 450
    ollama: OllamaConfig = field(default_factory=OllamaConfig)
    filter: FilterConfig = field(default_factory=FilterConfig)
    hackernews: HackerNewsConfig = field(default_factory=HackerNewsConfig)
    huggingface: HuggingFaceConfig = field(default_factory=HuggingFaceConfig)
    rss: RssConfig = field(default_factory=RssConfig)
    leetcode: LeetCodeConfig = field(default_factory=LeetCodeConfig)

    @property
    def db_path(self) -> Path:
        return Path(self.data_dir).expanduser() / "dailygrad.db"

    @property
    def digest_dir(self) -> Path:
        return Path(self.data_dir).expanduser() / "digests"

    @property
    def run_archive_dir(self) -> Path:
        return self.digest_dir / "runs"

    @property
    def latest_markdown_path(self) -> Path:
        return Path(self.data_dir).expanduser() / "latest.md"

    @property
    def latest_json_path(self) -> Path:
        return Path(self.data_dir).expanduser() / "latest.json"

    @property
    def source_preferences_path(self) -> Path:
        return Path(self.data_dir).expanduser() / "source_preferences.json"

    @property
    def leetcode_preferences_path(self) -> Path:
        return Path(self.data_dir).expanduser() / "leetcode_preferences.json"


def find_config_file(path: Path | None = None) -> Path | None:
    """The config file to use: `path`, else $DAILYGRAD_CONFIG, else ./dailygrad.toml, else None (defaults)."""
    if path is None and os.environ.get(CONFIG_ENV_VAR):
        path = Path(os.environ[CONFIG_ENV_VAR])
    if path is None and Path(DEFAULT_CONFIG_FILE).exists():
        path = Path(DEFAULT_CONFIG_FILE)
    return path


def load_config(path: Path | None = None) -> Config:
    """Load settings from the file chosen by find_config_file, on top of the built-in defaults."""
    path = find_config_file(path)
    config = Config()
    if path is None:
        return config

    try:
        with open(path, "rb") as file:
            raw = tomllib.load(file)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"cannot read config file {path}: {exc}") from exc

    _apply(config, raw, prefix="")
    if "feeds" in raw.get("rss", {}):  # TOML gives plain tables; the defaults are already Feed objects
        try:
            config.rss.feeds = [Feed(**feed) for feed in config.rss.feeds]
        except TypeError as exc:
            raise ConfigError("each [[rss.feeds]] entry needs a name and a url, and may have link_hosts") from exc
        for feed in config.rss.feeds:
            hosts = feed.link_hosts
            if not (isinstance(hosts, list) and all(isinstance(host, str) for host in hosts)):
                raise ConfigError(f"link_hosts of the feed {feed.name!r} must be a list of host names")

    if config.final_story_count < 1:
        raise ConfigError("final_story_count must be at least 1")
    if config.filter.shortlist_size < config.final_story_count:
        raise ConfigError("filter.shortlist_size must be at least final_story_count")
    for name in ("rss.max_candidates", "rss.max_per_feed", "huggingface.max_candidates", "hackernews.max_candidates"):
        section, key = name.split(".")
        if getattr(getattr(config, section), key) < 1:
            raise ConfigError(f"{name} must be at least 1")
    if config.run_budget_seconds < 1 or config.ollama.timeout_seconds < 1:
        raise ConfigError("run_budget_seconds and ollama.timeout_seconds must be at least 1")
    if config.hackernews.keyword_boost < 1:
        raise ConfigError("hackernews.keyword_boost must be at least 1")
    rotation = config.leetcode.rotation
    if not rotation or not all(track in LEETCODE_TRACKS for track in rotation):
        raise ConfigError(f"leetcode.rotation must list one or more of: {', '.join(LEETCODE_TRACKS)}")
    if config.leetcode.feedback_budget_seconds < 1 or config.leetcode.keep_alive_seconds < 0:
        raise ConfigError("leetcode.feedback_budget_seconds must be at least 1 and leetcode.keep_alive_seconds 0 or more")
    return config


def _apply(target, values: dict, prefix: str) -> None:
    """Copy TOML values onto a config dataclass, rejecting unknown keys and wrong types."""
    for key, value in values.items():
        if not hasattr(target, key):
            raise ConfigError(f"unknown setting: {prefix}{key}")
        current = getattr(target, key)
        if isinstance(current, float) and type(value) is int:
            value = float(value)  # let `temperature = 0` mean 0.0
        if is_dataclass(current):
            if not isinstance(value, dict):
                raise ConfigError(f"{prefix}{key} must be a table")
            _apply(current, value, prefix=f"{prefix}{key}.")
        elif not isinstance(value, type(current)):
            raise ConfigError(f"{prefix}{key} must be of type {type(current).__name__}")
        else:
            setattr(target, key, value)
