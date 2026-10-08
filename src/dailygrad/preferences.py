"""Source preferences: which of the available news sources a run fetches.

The preferences live in <data_dir>/source_preferences.json, next to the database, so they
are runtime data: Git never touches them and they survive a code update. The file holds
one of two lists:

    "disabled": [...]      every source is on except these; a source added later is on
    "enabled_only": [...]  only these are on; a source added later stays off

Without a file every source is on. `dailygrad sources set` writes the second form, because
"only these" has to stay true when a new source appears; `set all` returns to the first.

A run reads the file once, before fetching. A file that exists but cannot be understood
stops the run: guessing could fetch a source the user switched off. Changes are made
through `dailygrad sources`, which accepts only known source and group IDs.
"""

import json
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from dailygrad.config import Config
from dailygrad.output import write_atomic
from dailygrad.sources import ALL, GROUPS, Source, available_sources

log = logging.getLogger(__name__)

VERSION = 1
ACTIONS = ("enable", "disable", "set")
ALL_EXCEPT, ONLY = "all_except", "only"  # the two modes, named after what the stored list means
KEYS = {ALL_EXCEPT: "disabled", ONLY: "enabled_only"}
RECOVERY = "the file was left as it is; `dailygrad sources set all` (or `set` with the IDs you want) replaces it"


class PreferencesError(Exception):
    """A request that was refused, or a preferences file that cannot be used. Nothing was changed."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def read(path: Path) -> tuple[str, set[str]]:
    """The mode and its list of IDs. A missing file is the default: every source on.

    Raises PreferencesError for a file that exists but cannot be read or understood.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ALL_EXCEPT, set()
    except (OSError, UnicodeDecodeError) as exc:
        raise PreferencesError("invalid_preferences", f"cannot read {path}: {exc}; {RECOVERY}") from exc
    try:
        document = json.loads(text)
    except ValueError:
        document = None
    if isinstance(document, dict) and document.get("version") == VERSION:
        present = [mode for mode, key in KEYS.items() if key in document]
        if len(present) == 1:  # both lists at once would be ambiguous
            ids = document[KEYS[present[0]]]
            if isinstance(ids, list) and all(isinstance(id, str) for id in ids):
                return present[0], set(ids)
    raise PreferencesError("invalid_preferences", f"{path} is not a valid source preferences file; {RECOVERY}")


def disabled_for_run(config: Config, sources: list[Source]) -> set[str]:
    """The sources a run must skip. Read once, so the whole run uses one snapshot.

    Raises PreferencesError if the file exists but cannot be used.
    """
    disabled = _disabled(*read(config.source_preferences_path), sources)
    if sources and len(disabled) == len(sources):
        log.warning("every available source is switched off; the digest will have no news")
    return disabled


def _disabled(mode: str, ids: set[str], sources: list[Source]) -> set[str]:
    """The available sources that are off. An ID in the file that no longer exists is ignored."""
    everything = {source.id for source in sources}
    return everything & ids if mode == ALL_EXCEPT else everything - ids


def snapshot(sources: list[Source], disabled: set[str]) -> list[dict]:
    """The sources as plain data, for JSON output."""
    return [
        {"id": source.id, "name": source.name, "group": source.group, "enabled": source.id not in disabled}
        for source in sources
    ]


def status(config: Config) -> dict:
    """The sources and whether each is on, as a run started now would see them."""
    sources = available_sources(config)
    mode, ids = read(config.source_preferences_path)
    return _result(config, sources, mode, _disabled(mode, ids, sources), changed=False)


def change(config: Config, action: str, names: list[str]) -> dict:
    """Enable or disable the named sources and groups, or `set` them as the only enabled ones.

    `set` makes the selection exclusive, so sources added later stay off; `set all` goes back
    to the default, where they are on. `enable` and `disable` keep whichever mode is in effect.

    Raises PreferencesError, changing nothing, if a name is unknown, if no source would be
    left enabled, or if the existing file cannot be used (`set` replaces such a file).
    """
    if action not in ACTIONS:
        raise ValueError(f"unknown action: {action}")
    sources = available_sources(config)
    chosen = _expand(names, sources)
    everything = {source.id for source in sources}
    path = config.source_preferences_path

    with _locked(path):  # so two updates cannot each overwrite the other's change
        if action == "set":
            try:
                before = read(path)
            except PreferencesError:
                before = None  # the whole selection is being replaced, so the old file is not needed
            wants_all = any(name.strip().lower() == ALL for name in names)
            mode, ids = (ALL_EXCEPT, set()) if wants_all else (ONLY, chosen)
        else:
            before = mode, ids = read(path)
            adding = (action == "enable") == (mode == ONLY)  # enabling adds to "only", removes from "all except"
            ids = (ids | chosen if adding else ids - chosen) & everything
        disabled = _disabled(mode, ids, sources)
        if disabled == everything:
            raise PreferencesError("no_sources_enabled", "at least one source must stay enabled")

        changed = before is None or (mode, _disabled(mode, ids, sources)) != (before[0], _disabled(*before, sources))
        if changed:
            document = {
                "version": VERSION,
                KEYS[mode]: [source.id for source in sources if source.id in ids],
                "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            write_atomic(path, json.dumps(document, indent=2) + "\n")
    return _result(config, sources, mode, disabled, changed)


def _expand(names: list[str], sources: list[Source]) -> set[str]:
    """Turn source and group IDs into source IDs, rejecting any that are not known."""
    ids, unknown = set(), []
    for name in names:
        key = name.strip().lower()
        if key == ALL:
            ids.update(source.id for source in sources)
        elif key in GROUPS:
            ids.update(source.id for source in sources if source.group == key)
        elif any(source.id == key for source in sources):
            ids.add(key)
        else:
            unknown.append(name)
    if unknown:
        known = ", ".join([source.id for source in sources] + list(GROUPS) + [ALL])
        raise PreferencesError("unknown_source", f"unknown source or group: {', '.join(unknown)} (known: {known})")
    return ids


def _result(config: Config, sources: list[Source], mode: str, disabled: set[str], changed: bool) -> dict:
    groups = [
        {"id": id, "name": name, "sources": [source.id for source in sources if source.group == id]}
        for id, name in GROUPS.items()
    ]
    return {
        "ok": True,
        "changed": changed,
        "mode": mode,
        "sources": snapshot(sources, disabled),
        "groups": groups,
        "preferences_file": str(config.source_preferences_path.resolve()),
    }


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    """Hold an exclusive lock on a file beside `path` while a change is read, decided and written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.with_name(f".{path.name}.lock"), "a+") as lock:
        if os.name == "nt":
            import msvcrt

            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)  # waits up to ten seconds
        else:
            import fcntl

            fcntl.flock(lock, fcntl.LOCK_EX)
        yield  # closing the file releases the lock
