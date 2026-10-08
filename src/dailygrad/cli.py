"""Command-line interface: `dailygrad run`, `config`, `sources`, `history` and `reset-story-memory`."""

import argparse
import json
import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from dailygrad import __version__, db, history, pipeline, preferences
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
    add_history_command(commands, config_option)
    reset = commands.add_parser(
        "reset-story-memory",
        parents=[config_option],
        help="let stories that were already shown be shown again; history is kept",
        description="Start story selection afresh: stories shown in earlier digests may be chosen again. "
        "Runs, archives, summaries and lessons are all kept, and duplicate prevention carries on from the "
        "next run. Without --confirm this only shows what would happen.",
    )
    how = reset.add_mutually_exclusive_group()
    how.add_argument("--dry-run", action="store_true", help="show what a reset would do and change nothing (the default)")
    how.add_argument("--confirm", action="store_true", help="perform the reset")
    args = parser.parse_args(argv)
    config_path = getattr(args, "config", None)

    # Logs go to stderr so stdout carries only the digest.
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s: %(message)s")

    try:
        config = load_config(config_path)
        available_sources(config)  # rejects feed names that cannot be told apart
    except ConfigError as exc:
        if args.command in ("sources", "history") and getattr(args, "json", False):
            print(json.dumps({"ok": False, "error": {"code": "invalid_config", "message": str(exc)}}, indent=2))
        print(f"dailygrad: {exc}", file=sys.stderr)
        return 2

    if args.command == "config":
        print(describe(config, find_config_file(config_path)))
        return 0
    if args.command == "sources":
        return sources_command(config, args.action or "list", getattr(args, "names", []), getattr(args, "json", False))
    if args.command == "history":
        return history_command(config, args)
    if args.command == "reset-story-memory":
        return reset_story_memory_command(config, args.confirm)

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
        ("Run archives", f"{config.run_archive_dir.resolve() / 'YYYY-MM-DD' / 'run-ID-TIME'}.md and .json"),
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


def reset_story_memory_command(config: Config, confirmed: bool) -> int:
    """Preview a story-memory reset, or perform it when confirmed. Exits with 1 if the database cannot be used."""
    path = config.db_path
    try:
        memory = db.story_memory(path)
        print(f"Database:            {path.resolve()}")
        if not memory["exists"]:
            print("There is no database yet, so there is no story memory to reset. Nothing was changed.")
            return 0
        print(f"Runs recorded:       {memory['runs']}")
        print(f"Earlier resets:      {memory['resets']}" + (f" (last {memory['last_reset_at']})" if memory["resets"] else ""))
        print(f"Stories remembered:  {memory['remembered']} (shown already, so held back from future digests)")
        print()
        if not memory["remembered"]:
            print("No story is being held back, so there is nothing to reset. Nothing was changed.")
            return 0
        if not confirmed:
            print(f"A reset would let those {memory['remembered']} stories be chosen again if a source still offers them.")
            print("It keeps every run, archive, summary and lesson, and the curriculum carries on where it is.")
            print("Dry run: nothing was changed. To reset, run: dailygrad reset-story-memory --confirm")
            return 0
        conn = db.connect(path)
        try:
            freed = db.reset_story_memory(conn, datetime.now(timezone.utc))
        finally:
            conn.close()
    except (db.sqlite3.Error, OSError) as exc:
        print(f"dailygrad: cannot use the database {path}: {exc}", file=sys.stderr)
        return 1
    print(f"Story memory reset: {freed} stories may be shown again. A story shown from now on is not repeated.")
    print("Every run, archive, summary and lesson was kept. No digest was generated.")
    return 0


def add_history_command(commands, config_option: argparse.ArgumentParser) -> None:
    json_option = argparse.ArgumentParser(add_help=False)
    json_option.add_argument(
        "--json", action="store_true", default=argparse.SUPPRESS, help="print the result as JSON, for another program"
    )
    date_option = argparse.ArgumentParser(add_help=False)
    date_option.add_argument(
        "--date", default=argparse.SUPPRESS, metavar="YYYY-MM-DD", help="only the runs of this day"
    )
    listing = [config_option, json_option, date_option]
    command = commands.add_parser(
        "history",
        parents=listing,
        help="list, show or backfill the archived digest of every run",
        description="Every run's digest is archived once and never replaced, so a second run on the same "
        "day does not lose the first. List the archived runs, print one, or archive digests written before "
        "archives existed.",
    )
    actions = command.add_subparsers(dest="action")
    actions.add_parser("list", parents=listing, help="list the archived runs, oldest first (the default)")
    show = actions.add_parser("show", parents=[config_option, date_option], help="print one archived run's digest")
    show.add_argument("run_id", type=int, metavar="RUN_ID")
    show.add_argument("--markdown", action="store_true", help="print the Markdown digest instead of the JSON document")
    actions.add_parser(
        "backfill",
        parents=[config_option, json_option],
        help="archive latest.* and the dated digests that have no archive yet; nothing is invented",
    )


def history_command(config: Config, args: argparse.Namespace) -> int:
    """List archived runs, print one, or backfill. Exits with 2 if the request is refused, 1 if a file failed."""
    action, as_json, day = args.action or "list", getattr(args, "json", False), getattr(args, "date", None)
    try:
        if day is not None and (len(day) != 10 or date.fromisoformat(day).isoformat() != day):
            raise ValueError
    except ValueError:
        return _history_refused(history.HistoryError("bad_date", f"--date must be YYYY-MM-DD, got {day!r}"), as_json)

    try:
        if action == "show":
            run = history.find_run(config, args.run_id, day)
            if args.markdown and not run["markdown"]:
                raise history.HistoryError("no_markdown", f"run {args.run_id} was archived without its Markdown")
            print(Path(run["markdown" if args.markdown else "json"]).read_text(encoding="utf-8"), end="")
            return 0
        if action == "backfill":
            results = history.backfill(config)
            if as_json:
                print(json.dumps({"ok": True, "results": results}, indent=2))
            else:
                print(backfill_report(results))
            return 0
        runs = history.archived_runs(config, day)
        missing = history.unarchived_runs(config, runs, day)
    except history.HistoryError as exc:
        return _history_refused(exc, as_json)
    except OSError as exc:
        if as_json:
            print(json.dumps({"ok": False, "error": {"code": "read_failed", "message": str(exc)}}, indent=2))
        print(f"dailygrad: {exc}", file=sys.stderr)
        return 1

    if as_json:
        print(json.dumps({"ok": True, "runs": runs, "not_archived": missing}, indent=2))
    else:
        print(history_table(runs, missing))
    return 0


def _history_refused(exc: history.HistoryError, as_json: bool) -> int:
    if as_json:
        print(json.dumps({"ok": False, "error": {"code": exc.code, "message": str(exc)}}, indent=2))
    print(f"dailygrad: {exc}", file=sys.stderr)
    return 2


def history_table(runs: list[dict], missing: list[dict]) -> str:
    lines = []
    if runs:
        rows = [("Date", "Run", "Generated", "Status", "Stories", "Lesson")]
        for run in runs:
            lesson = "yes" if run["has_lesson"] else "no"
            stories, status = str(run["story_count"]), str(run["status"])
            rows.append((run["date"], str(run["run_id"]), run["generated_at"], status, stories, lesson))
        widths = [max(len(row[column]) for row in rows) for column in range(5)]
        lines += ["  ".join([*(cell.ljust(width) for cell, width in zip(row, widths)), row[5]]) for row in rows]
    else:
        lines.append("No archived runs.")
    if missing:
        ids = ", ".join(f"{run['run_id']} ({run['date']})" for run in missing)
        lines += ["", f"Recorded in the database but not archived, so their digests are not available: {ids}"]
    return "\n".join(lines)


def backfill_report(results: list[dict]) -> str:
    if not results:
        return "No digest files to archive."
    lines = []
    for result in results:
        if result["outcome"] == "skipped":
            lines.append(f"skipped   {result['source']}: {result['reason']}")
            continue
        note = "" if result["markdown"] else " (JSON only: no matching Markdown)"
        label = "archived " if result["outcome"] == "archived" else "already   "
        lines.append(f"{label} run {result['run_id']} of {result['date']}{note}")
    return "\n".join(lines)


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
