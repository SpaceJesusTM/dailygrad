"""Configuration: built-in defaults, optionally overridden by a TOML file."""

import os
import tomllib
from dataclasses import dataclass, field, is_dataclass
from pathlib import Path

DEFAULT_CONFIG_FILE = "dailygrad.toml"
CONFIG_ENV_VAR = "DAILYGRAD_CONFIG"

# Matched as whole words (plural allowed) against Hacker News titles only.
DEFAULT_KEYWORDS = [
    "AI", "AGI", "LLM", "GPT", "machine learning", "deep learning", "neural",
    "transformer", "diffusion", "language model", "foundation model",
    "fine-tuning", "embedding", "RAG", "agent", "agentic", "reinforcement learning",
    "OpenAI", "Anthropic", "DeepMind", "Claude", "Gemini", "Llama", "Mistral",
    "Qwen", "DeepSeek", "Hugging Face", "Ollama", "PyTorch", "MCP",
]  # fmt: skip


class ConfigError(ValueError):
    pass


@dataclass
class Feed:
    name: str
    url: str


DEFAULT_FEEDS = [
    Feed("OpenAI", "https://openai.com/news/rss.xml"),
    Feed("Google DeepMind", "https://deepmind.google/blog/rss.xml"),
    Feed("Google Research", "https://research.google/blog/rss/"),
    Feed("Hugging Face Blog", "https://huggingface.co/blog/feed.xml"),
]


@dataclass
class FilterConfig:
    max_age_hours: int = 48
    shortlist_size: int = 15
    keywords: list[str] = field(default_factory=lambda: list(DEFAULT_KEYWORDS))


@dataclass
class HackerNewsConfig:
    enabled: bool = True
    min_points: int = 50


@dataclass
class HuggingFaceConfig:
    enabled: bool = True
    min_upvotes: int = 5


@dataclass
class RssConfig:
    feeds: list[Feed] = field(default_factory=lambda: list(DEFAULT_FEEDS))


@dataclass
class OllamaConfig:
    url: str = "http://localhost:11434"
    model: str = "qwen3.5:4b-q4_K_M"
    context_tokens: int = 8192
    temperature: float = 0.2
    think: bool = False
    timeout_seconds: int = 180  # per model request; the first one includes loading the model


@dataclass
class Config:
    data_dir: str = "data"  # relative paths resolve against the working directory
    ollama: OllamaConfig = field(default_factory=OllamaConfig)
    filter: FilterConfig = field(default_factory=FilterConfig)
    hackernews: HackerNewsConfig = field(default_factory=HackerNewsConfig)
    huggingface: HuggingFaceConfig = field(default_factory=HuggingFaceConfig)
    rss: RssConfig = field(default_factory=RssConfig)

    @property
    def db_path(self) -> Path:
        return Path(self.data_dir).expanduser() / "dailygrad.db"

    @property
    def digest_dir(self) -> Path:
        return Path(self.data_dir).expanduser() / "digests"


def load_config(path: Path | None = None) -> Config:
    """Load settings from `path`, else $DAILYGRAD_CONFIG, else ./dailygrad.toml, else defaults."""
    if path is None and os.environ.get(CONFIG_ENV_VAR):
        path = Path(os.environ[CONFIG_ENV_VAR])
    if path is None and Path(DEFAULT_CONFIG_FILE).exists():
        path = Path(DEFAULT_CONFIG_FILE)

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
            raise ConfigError("each [[rss.feeds]] entry needs exactly a name and a url") from exc
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
