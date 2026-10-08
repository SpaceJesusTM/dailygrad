"""Run archives: every digest a run wrote, kept under digests/runs/ and never replaced.

The dated files hold the last run of each day, and latest.md and latest.json the last run of
all. A second run on the same day replaces them, so the archives are where each run survives:

    <data_dir>/digests/runs/YYYY-MM-DD/run-<run id>-<UTC time>.json
    <data_dir>/digests/runs/YYYY-MM-DD/run-<run id>-<UTC time>.md

with the same bytes as that run's latest.json and latest.md. The file name carries the run's
whole identity (date, run id and generated_at), so a run after a database reset, which starts
again at run 1, gets a name of its own. An archive is created once and never written again.
The layout is documented in docs/output.md.
"""

import json
import logging
import os
from datetime import date, datetime, timezone
from pathlib import Path

from dailygrad import db
from dailygrad.config import Config
from dailygrad.render import describes

log = logging.getLogger(__name__)


class HistoryError(Exception):
    """An archive request that is refused. `code` is stable; the message is for a person."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def archive_paths(config: Config, document: dict) -> tuple[Path, Path]:
    """Where a digest document's archive lives, as (JSON, Markdown). Raises HistoryError if it names no run."""
    run_id, day, generated = document.get("run_id"), document.get("date"), document.get("generated_at")
    try:
        if type(run_id) is not int or run_id < 1 or not isinstance(day, str) or not isinstance(generated, str):
            raise ValueError
        if date.fromisoformat(day).isoformat() != day:
            raise ValueError
        stamp = datetime.fromisoformat(generated).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    except ValueError:
        raise HistoryError("invalid_digest", "the document has no usable run_id, date and generated_at") from None
    base = config.run_archive_dir / day / f"run-{run_id}-{stamp}"
    return base.with_name(base.name + ".json"), base.with_name(base.name + ".md")


def archive_run(config: Config, markdown: str | None, json_text: str) -> list[Path]:
    """Archive one run's digest. Returns the files this call created: none if it was archived already.

    The Markdown is written first, so an archive's JSON file means the pair is complete.
    """
    json_path, markdown_path = archive_paths(config, json.loads(json_text))
    created = []
    try:
        if markdown is not None and _write_new(markdown_path, markdown):
            created.append(markdown_path)
        if _write_new(json_path, json_text):
            created.append(json_path)
    except BaseException:
        discard(created)
        raise
    return created


def discard(created: list[Path]) -> None:
    """Remove archive files that archive_run just created, for a run that is not going to be recorded."""
    for path in created:
        path.unlink(missing_ok=True)


def _write_new(path: Path, text: str) -> bool:
    """Create `path` holding `text`, complete or not at all. False if it already holds exactly that.

    An existing file is never replaced: one with other content is a HistoryError. The text goes
    to a temporary file that is then linked into place, which fails if the name is taken.
    """
    data = text.encode("utf-8")
    if path.exists():
        return _same_or_conflict(path, data)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with open(temporary, "wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            return _same_or_conflict(path, data)
        except OSError:  # a filesystem without hard links: the check above is the only guard
            os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return True


def _same_or_conflict(path: Path, data: bytes) -> bool:
    if path.read_bytes() != data:
        raise HistoryError("archive_conflict", f"{path} already exists with different content; it was left as it is")
    return False


def archived_runs(config: Config, day: str | None = None) -> list[dict]:
    """Every archived run, oldest first, or only those of `day` (YYYY-MM-DD). Unusable files are skipped."""
    root = config.run_archive_dir
    if day is not None:
        directories = [root / day]
    else:
        directories = sorted(path for path in root.iterdir() if path.is_dir()) if root.is_dir() else []
    runs = []
    for directory in directories:
        for path in directory.glob("run-*.json") if directory.is_dir() else ():
            entry = _entry(config, path)
            if entry:
                runs.append(entry)
    return sorted(runs, key=lambda run: (run["date"], datetime.fromisoformat(run["generated_at"]), run["run_id"]))


def _entry(config: Config, path: Path) -> dict | None:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict) or archive_paths(config, document)[0] != path:
            raise ValueError("its name does not match the run it holds")
        stories = document["stories"]
        if not isinstance(stories, list):
            raise ValueError("it has no stories list")
        entry = {
            "run_id": document["run_id"],
            "date": document["date"],
            "generated_at": document["generated_at"],
            "status": document.get("status"),
            "story_count": len(stories),
            "has_lesson": isinstance(document.get("lesson"), dict),
            "json": str(path.resolve()),
            "markdown": None,
        }
    except (OSError, ValueError, KeyError, TypeError, HistoryError) as exc:
        log.warning("skipping %s: %s", path, exc)
        return None
    markdown = path.with_suffix(".md")
    if markdown.is_file():
        entry["markdown"] = str(markdown.resolve())
    return entry


def unarchived_runs(config: Config, archived: list[dict], day: str | None = None) -> list[dict]:
    """Runs the database records that have no archive: their digests were replaced before archives existed."""
    have = {(run["run_id"], run["date"]) for run in archived}
    return [
        {"run_id": run_id, "date": run_date, "recorded_at": created_at}
        for run_id, run_date, created_at in db.recorded_runs(config.db_path)
        if (run_id, run_date) not in have and day in (None, run_date)
    ]


def find_run(config: Config, run_id: int, day: str | None = None) -> dict:
    """The archived run with this ID, on `day` if given. Raises HistoryError if there is none, or more than one."""
    matches = [run for run in archived_runs(config, day) if run["run_id"] == run_id]
    where = f" on {day}" if day else ""
    if not matches:
        raise HistoryError("not_found", f"no archived run {run_id}{where}")
    if len(matches) > 1:  # the database was reset, so the ID was used twice
        files = ", ".join(run["json"] for run in matches)
        raise HistoryError("ambiguous_run", f"more than one archived run {run_id}{where}: {files}")
    return matches[0]


def backfill(config: Config) -> list[dict]:
    """Archive the digests still on disk that have no archive: latest.* and each day's dated pair.

    Only complete documents that are really there are archived, byte for byte. A run whose
    files were already replaced by a later run is gone, and nothing is made up in its place.
    """
    candidates = [(config.latest_json_path, config.latest_markdown_path)]
    candidates += [(path, path.with_suffix(".md")) for path in sorted(config.digest_dir.glob("*.json"))]
    results, seen = [], set()
    for json_path, markdown_path in candidates:
        if not json_path.is_file():
            continue
        result = _archive_existing(config, json_path, markdown_path)
        key = (result.get("run_id"), result.get("generated_at"))
        if result["outcome"] == "skipped" or key not in seen:  # latest.json is also its day's dated file
            seen.add(key)
            results.append(result)
    return results


def preserve_latest(config: Config) -> None:
    """Archive the digest in latest.* if it has no archive, before a new run replaces it. Never raises."""
    if config.latest_json_path.is_file():
        result = _archive_existing(config, config.latest_json_path, config.latest_markdown_path)
        if result["outcome"] == "skipped":
            log.warning("the previous digest was not archived: %s", result["reason"])


def _archive_existing(config: Config, json_path: Path, markdown_path: Path) -> dict:
    result = {"source": str(json_path.resolve()), "outcome": "skipped", "markdown": False}
    try:
        json_text = json_path.read_text(encoding="utf-8")
        document = json.loads(json_text)
        if not isinstance(document, dict) or not isinstance(document.get("stories"), list):
            raise HistoryError("invalid_digest", "it is not a digest document")
        archive_json, archive_markdown = archive_paths(config, document)
        result.update(run_id=document["run_id"], date=document["date"], generated_at=document["generated_at"])
        dated = json_path != config.latest_json_path
        if dated and json_path.stem != document["date"]:
            raise HistoryError("invalid_digest", f"it is dated {document['date']}, unlike its file name")
        # The Markdown is kept only if it is this digest's: after a failed write the pair can differ.
        markdown = markdown_path.read_text(encoding="utf-8") if markdown_path.is_file() else None
        if markdown is not None and not describes(markdown, document):
            markdown = None
        created = archive_run(config, markdown, json_text)
        result["outcome"] = "archived" if archive_json in created else "already_archived"
        result["markdown"] = archive_markdown.is_file()
        result["json"] = str(archive_json.resolve())
    except (OSError, ValueError, HistoryError) as exc:
        result["reason"] = str(exc)
    return result
