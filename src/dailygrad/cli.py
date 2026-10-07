"""Command-line interface: `dailygrad run`."""

import argparse
import logging
import sys
from pathlib import Path

from dailygrad import pipeline
from dailygrad.config import CONFIG_ENV_VAR, DEFAULT_CONFIG_FILE, ConfigError, load_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dailygrad", description="Daily AI briefing and micro-learning.")
    commands = parser.add_subparsers(dest="command", required=True)
    run_parser = commands.add_parser("run", help="fetch news, write today's digest and print it")
    run_parser.add_argument(
        "--config",
        type=Path,
        help=f"path to a TOML config file (default: ${CONFIG_ENV_VAR}, then ./{DEFAULT_CONFIG_FILE})",
    )
    args = parser.parse_args(argv)

    # Logs go to stderr so stdout carries only the digest.
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s: %(message)s")

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"dailygrad: {exc}", file=sys.stderr)
        return 2

    digest, model_ok = pipeline.run(config)
    print(digest, end="")
    return 0 if model_ok else 1  # non-zero tells a scheduler the digest is degraded


if __name__ == "__main__":
    sys.exit(main())
