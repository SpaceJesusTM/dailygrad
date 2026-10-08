"""Source adapters, and the registry that names them.

Each adapter module has fetch() (does the HTTP request) and parse() (pure).
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

from dailygrad.config import Config, ConfigError
from dailygrad.models import Candidate
from dailygrad.sources import hackernews, huggingface, rss

# Groups let several sources be switched together. "all" is every available source.
ALL = "all"
GROUPS = {
    "labs": "AI labs and research",
    "hugging-face": "Hugging Face",
    "community": "Community",
}
# The group of each built-in source. A feed you add yourself belongs to no group.
SOURCE_GROUPS = {
    "openai": "labs",
    "google-deepmind": "labs",
    "google-research": "labs",
    "anthropic-news": "labs",
    "meta-ai-research": "labs",
    "nvidia-developer-blog": "labs",
    "mistral-ai-news": "labs",
    "microsoft-research": "labs",
    "hugging-face-blog": "hugging-face",
    "hugging-face-daily-papers": "hugging-face",
    "hacker-news": "community",
}


@dataclass(frozen=True)
class Source:
    id: str  # stable identifier, derived from the name: "Google DeepMind" -> "google-deepmind"
    name: str  # as shown in the digest
    group: str | None
    fetch: Callable[[], list[Candidate]]


def source_id(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def available_sources(config: Config) -> list[Source]:
    """Every source the configuration provides, whether or not it is switched on.

    The order is the fetch order, and it matters: deduplication keeps the first copy of a
    story, so the official feed or the paper entry is preferred over a Hacker News link
    to the same thing.
    """
    named = [(feed.name, partial(rss.fetch, feed)) for feed in config.rss.feeds]
    if config.huggingface.enabled:
        named.append(("Hugging Face Daily Papers", huggingface.fetch))
    if config.hackernews.enabled:
        named.append(("Hacker News", hackernews.fetch))

    sources: list[Source] = []
    for name, fetch in named:
        id = source_id(name)
        if not id or id == ALL or id in GROUPS:
            raise ConfigError(f"the feed name {name!r} cannot be used: its ID {id!r} is empty or reserved")
        if any(source.id == id for source in sources):
            raise ConfigError(f"two sources share the ID {id!r}: give the feed {name!r} a different name")
        sources.append(Source(id, name, SOURCE_GROUPS.get(id), fetch))
    return sources
