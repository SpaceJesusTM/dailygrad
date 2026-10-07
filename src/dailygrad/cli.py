"""Command-line interface: `dailygrad run` and `dailygrad config`."""

import argparse
import logging
import sys
from pathlib import Path

from dailygrad import __version__, pipeline
from dailygrad.config import CONFIG_ENV_VAR, DEFAULT_CONFIG_FILE, Config, ConfigError, find_config_file, load_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dailygrad", description="Daily AI briefing and micro-learning.")
    parser.add_argument("--version", action="version", version=f"dailygrad {__version__}")
    config_option = argparse.ArgumentParser(add_help=False)
    config_option.add_argument(
        "--config",
        type=Path,
        help=f"path to a TOML config file (default: ${CONFIG_ENV_VAR}, then ./{DEFAULT_CONFIG_FILE})",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("run", parents=[config_option], help="fetch news, write today's digest and print it")
    commands.add_parser("config", parents=[config_option], help="show the settings a run would use, and where files go")
    args = parser.parse_args(argv)

    # Logs go to stderr so stdout carries only the digest.
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s: %(message)s")

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"dailygrad: {exc}", file=sys.stderr)
        return 2

    if args.command == "config":
        print(describe(config, find_config_file(args.config)))
        return 0

    digest, model_ok = pipeline.run(config)
    print(digest, end="")
    return 0 if model_ok else 1  # non-zero tells a scheduler the digest is degraded


def describe(config: Config, config_file: Path | None) -> str:
    """The settings in effect, with every path made absolute."""
    sources = [feed.name for feed in config.rss.feeds]
    if config.huggingface.enabled:
        sources.append("Hugging Face Daily Papers")
    if config.hackernews.enabled:
        sources.append("Hacker News")
    rows = [
        ("Config file", config_file.resolve() if config_file else "none (built-in defaults)"),
        ("Database", config.db_path.resolve()),
        ("Dated digests", f"{config.digest_dir.resolve() / 'YYYY-MM-DD'}.md and .json"),
        ("Latest digest", config.latest_markdown_path.resolve()),
        ("Latest JSON", config.latest_json_path.resolve()),
        ("Ollama endpoint", config.ollama.url),
        ("Ollama model", config.ollama.model),
        ("Stories per digest", f"{config.final_story_count}, chosen from up to {config.filter.shortlist_size} candidates"),
        ("Sources", ", ".join(sources) or "none"),
    ]
    return "\n".join(f"{label + ':':20}{value}" for label, value in rows)


if __name__ == "__main__":
    sys.exit(main())
