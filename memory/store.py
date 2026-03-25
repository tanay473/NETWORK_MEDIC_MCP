"""
memory/store.py
Single read/write gateway for all persistent state in network_medic.
No module should import from memory/data/*.json directly — always go through here.

Manages:
  - action_log.json      : every executed action with outcome
  - state_history.json   : SystemState snapshots over time
  - rollback_log.json    : rollback events
  - user_feedback.json   : post-session feedback
"""

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utils.json_store import read, write, append_entry
from utils.logger import get_logger

log = get_logger(__name__)

# Data directory — all JSON files live here
_DATA_DIR = Path(__file__).resolve().parent / "data"

ACTION_LOG      = _DATA_DIR / "action_log.json"
STATE_HISTORY   = _DATA_DIR / "state_history.json"
ROLLBACK_LOG    = _DATA_DIR / "rollback_log.json"
USER_FEEDBACK   = _DATA_DIR / "user_feedback.json"


def _ensure_data_dir() -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)


# ── Action Log ────────────────────────────────────────────────────────────────

def log_action(entry: dict) -> None:
    """
    Append an action log entry. Caller must provide a dict conforming to log_schema.json.
    Adds entry_id and timestamp if not present.
    """
    _ensure_data_dir()
    entry.setdefault("entry_id", str(uuid.uuid4()))
    entry.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    append_entry(ACTION_LOG, entry)
    log.info(f"Action logged | action_type={entry.get('action_type')} status={entry.get('status')}")


def get_recent_actions(n: int = 10) -> list[dict]:
    """Returns the last n action log entries."""
    _ensure_data_dir()
    entries = read(ACTION_LOG)
    if not isinstance(entries, list):
        return []
    return entries[-n:]


# ── State History ─────────────────────────────────────────────────────────────

def save_state(state: dict) -> None:
    """Append a SystemState snapshot to state_history.json."""
    _ensure_data_dir()
    state.setdefault("snapshot_id", str(uuid.uuid4()))
    state.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    append_entry(STATE_HISTORY, state)
    log.debug(f"State snapshot saved | snapshot_id={state['snapshot_id']}")


def get_latest_state() -> dict | None:
    """Returns the most recent SystemState snapshot, or None if history is empty."""
    _ensure_data_dir()
    entries = read(STATE_HISTORY)
    if not isinstance(entries, list) or not entries:
        return None
    return entries[-1]


def get_state_history(n: int = 5) -> list[dict]:
    """Returns the last n state snapshots."""
    _ensure_data_dir()
    entries = read(STATE_HISTORY)
    if not isinstance(entries, list):
        return []
    return entries[-n:]


# ── Rollback Log ──────────────────────────────────────────────────────────────

def log_rollback(entry: dict) -> None:
    """Append a rollback event to rollback_log.json."""
    _ensure_data_dir()
    entry.setdefault("entry_id", str(uuid.uuid4()))
    entry.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    append_entry(ROLLBACK_LOG, entry)
    log.info(f"Rollback logged | action_type={entry.get('action_type')} result={entry.get('result')}")


# ── User Feedback ─────────────────────────────────────────────────────────────

def save_feedback(plan_id: str, feedback: str, notes: str = "") -> None:
    """
    Save user feedback for a completed session.
    feedback: 'helpful' | 'not_helpful' | 'neutral'
    """
    _ensure_data_dir()
    entry = {
        "entry_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "plan_id": plan_id,
        "feedback": feedback,
        "notes": notes,
    }
    append_entry(USER_FEEDBACK, entry)
    log.info(f"Feedback saved | plan_id={plan_id} feedback={feedback}")


def get_all_feedback() -> list[dict]:
    _ensure_data_dir()
    entries = read(USER_FEEDBACK)
    return entries if isinstance(entries, list) else []


# ── Generic ───────────────────────────────────────────────────────────────────

def clear_all() -> None:
    """
    Wipe all memory data. Used in tests only — not exposed via MCP.
    """
    for path in [ACTION_LOG, STATE_HISTORY, ROLLBACK_LOG, USER_FEEDBACK]:
        write(path, [])
    log.warning("All memory data cleared.")
