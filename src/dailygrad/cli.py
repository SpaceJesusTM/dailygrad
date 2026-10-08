"""Command-line interface: `dailygrad run`, `dailygrad config` and `dailygrad sources`."""

import argparse
import json
import logging
import sys
from pathlib import Path

from dailygrad import __version__, pipeline, preferences
from dailygrad.config import CONFIG_ENV_VAR, DEFAULT_CONFIG_FILE, Config, ConfigError, find_config_file, load_config
from dailygrad.sources import ALL, available_sources


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dailygrad", description="Daily AI briefing and micro-learning.")
    parser.add_argument("--version", action="version", version=f"dailygrad {__version__}")
    # SUPPRESS keeps a sub-command's unset option from overwriting one given before the sub-command.
    config_option = argparse.ArgumentParser(add_help=False)
    config_option.add_argument(
        "--config",
        type=Path,
        default=argparse.SUPPRESS,
        help=f"path to a TOML config file (default: ${CONFIG_ENV_VAR}, then ./{DEFAULT_CONFIG_FILE})",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("run", parents=[config_option], help="fetch news, write today's digest and print it")
    commands.add_parser("config", parents=[config_option], help="show the settings a run would use, and where files go")
    add_sources_command(commands, config_option)
    args = parser.parse_args(argv)
    config_path = getattr(args, "config", None)

    # Logs go to stderr so stdout carries only the digest.
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s: %(message)s")

    try:
        config = load_config(config_path)
        available_sources(config)  # rejects feed names that cannot be told apart
    except ConfigError as exc:
        if args.command == "sources" and getattr(args, "json", False):
            print(json.dumps({"ok": False, "error": {"code": "invalid_config", "message": str(exc)}}, indent=2))
        print(f"dailygrad: {exc}", file=sys.stderr)
        return 2

    if args.command == "config":
        print(describe(config, find_config_file(config_path)))
        return 0
    if args.command == "sources":
        return sources_command(config, args.action or "list", getattr(args, "names", []), getattr(args, "json", False))

    try:
        digest, model_ok = pipeline.run(config)
    except preferences.PreferencesError as exc:  # raised before anything is fetched or written
        print(f"dailygrad: {exc}", file=sys.stderr)
        return 2
    print(digest, end="")
    return 0 if model_ok else 1  # non-zero tells a scheduler the digest is degraded


def describe(config: Config, config_file: Path | None) -> str:
    """The settings in effect, with every path made absolute."""
    try:
        enabled = [source["name"] for source in preferences.status(config)["sources"] if source["enabled"]]
        sources = ", ".join(enabled) or "none"
    except preferences.PreferencesError as exc:
        sources = f"unknown: {exc}"
    rows = [
        ("Config file", config_file.resolve() if config_file else "none (built-in defaults)"),
        ("Database", config.db_path.resolve()),
        ("Dated digests", f"{config.digest_dir.resolve() / 'YYYY-MM-DD'}.md and .json"),
        ("Latest digest", config.latest_markdown_path.resolve()),
        ("Latest JSON", config.latest_json_path.resolve()),
        ("Ollama endpoint", config.ollama.url),
        ("Ollama model", config.ollama.model),
        ("Stories per digest", f"{config.final_story_count}, chosen from up to {config.filter.shortlist_size} candidates"),
        ("Sources", sources),
        ("Source preferences", config.source_preferences_path.resolve()),
    ]
    return "\n".join(f"{label + ':':20}{value}" for label, value in rows)


def add_sources_command(commands, config_option: argparse.ArgumentParser) -> None:
    json_option = argparse.ArgumentParser(add_help=False)
    json_option.add_argument(
        "--json", action="store_true", default=argparse.SUPPRESS, help="print the result as JSON, for another program"
    )
    options = [config_option, json_option]
    sources = commands.add_parser(
        "sources",
        parents=options,
        help="show or change which news sources are fetched",
        description="Show or change which news sources are fetched. Changes apply from the next run. "
        f"An ID is a source ID or a group ID, as listed by `dailygrad sources`, or `{ALL}`.",
    )
    actions = sources.add_subparsers(dest="action")
    actions.add_parser("list", parents=options, help="show every source and whether it is enabled (the default)")
    for action, text in (
        ("enable", "switch sources or groups on"),
        ("disable", "switch sources or groups off"),
        ("set", f"enable only these sources or groups, now and when sources are added; `set {ALL}` restores the default"),
    ):
        actions.add_parser(action, parents=options, help=text).add_argument("names", nargs="+", metavar="ID")


def sources_command(config: Config, action: str, names: list[str], as_json: bool) -> int:
    """List the sources or change which are enabled. Exits with 2 if the request is refused, 1 if saving failed."""
    try:
        result = preferences.status(config) if action == "list" else preferences.change(config, action, names)
    except (preferences.PreferencesError, OSError) as exc:
        refused = isinstance(exc, preferences.PreferencesError)
        code = exc.code if refused else "write_failed"
        if as_json:
            print(json.dumps({"ok": False, "error": {"code": code, "message": str(exc)}}, indent=2))
        print(f"dailygrad: {exc}", file=sys.stderr)
        return 2 if refused else 1

    if as_json:
        print(json.dumps(result, indent=2))
        return 0
    print(sources_table(result))
    if action != "list":
        print()
        if result["changed"]:
            print("Saved. The change applies from the next run; today's digest is not regenerated.")
        else:
            print("Nothing to change.")
    return 0


def sources_table(result: dict) -> str:
    rows = [("ID", "Source", "Group", "Status")]
    for source in result["sources"]:
        status = "enabled" if source["enabled"] else "disabled"
        rows.append((source["id"], source["name"], source["group"] or "-", status))
    widths = [max(len(row[column]) for row in rows) for column in range(3)]
    lines = ["  ".join([*(cell.ljust(width) for cell, width in zip(row, widths)), row[3]]) for row in rows]
    groups = [f"{group['id']} ({group['name']})" for group in result["groups"] if group["sources"]]
    lines += ["", f"Groups: {', '.join(groups + [ALL])}", f"Preferences file: {result['preferences_file']}"]
    if result["mode"] == preferences.ONLY:
        lines.append("Selection: only the sources enabled above. A source added later stays disabled.")
    else:
        lines.append("Selection: every source except those disabled above. A source added later is enabled.")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
