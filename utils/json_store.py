"""
utils/json_store.py
Low-level JSON file I/O with atomic writes and file locking.
memory/store.py builds on top of this — this layer has no domain knowledge,
it just handles files safely.
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from utils.logger import get_logger

log = get_logger(__name__)


def read(path: str | Path) -> Any:
    """
    Read and parse a JSON file.
    Returns empty dict if file does not exist.
    Raises ValueError on malformed JSON.
    """
    path = Path(path)

    if not path.exists():
        log.debug(f"json_store.read: file not found, returning {{}} | path={path}")
        return {}

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        log.debug(f"json_store.read: ok | path={path}")
        return data
    except json.JSONDecodeError as exc:
        log.error(f"json_store.read: malformed JSON | path={path} | {exc}")
        raise ValueError(f"Malformed JSON in {path}: {exc}") from exc


def write(path: str | Path, data: Any) -> None:
    """
    Atomically write data as JSON to path.
    Uses a temp file + rename to prevent partial writes on crash.
    Creates parent directories if they don't exist.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        # Write to temp file in same directory, then atomic rename
        tmp_fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str)
            os.replace(tmp_path, path)  # atomic on same filesystem
        except Exception:
            os.unlink(tmp_path)  # clean up temp on failure
            raise

        log.debug(f"json_store.write: ok | path={path}")

    except Exception as exc:
        log.error(f"json_store.write: failed | path={path} | {exc}")
        raise


def append_entry(path: str | Path, entry: Any) -> None:
    """
    Append a single entry to a JSON file that contains a list.
    If the file doesn't exist or is empty, initialises it as a list.

    Used for action_log.json, rollback_log.json, state_history.json.
    """
    path = Path(path)

    existing = read(path)
    if not isinstance(existing, list):
        log.warning(
            f"json_store.append_entry: expected list, got {type(existing).__name__}. "
            f"Reinitialising as list | path={path}"
        )
        existing = []

    existing.append(entry)
    write(path, existing)
    log.debug(f"json_store.append_entry: appended entry | path={path} | total={len(existing)}")
