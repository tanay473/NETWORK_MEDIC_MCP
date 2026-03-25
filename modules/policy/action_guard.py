"""
modules/policy/action_guard.py
Risk scoring, cooldown enforcement, and per-session action caps.
Runs per-action before the HIL approval gate.
"""

from datetime import datetime, timezone, timedelta

from memory.store import get_recent_actions
from utils.logger import get_logger

log = get_logger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

# Max number of actions allowed in a single session
SESSION_ACTION_CAP = 10

# Cooldown: minimum minutes between identical action_types
COOLDOWN_MINUTES: dict[str, int] = {
    "restart_network_interface": 5,
    "release_renew_dhcp":        3,
    "flush_dns":                 1,
    "reset_winsock":             10,
    "reset_tcp_ip":              10,
    "disable_interface":         5,
    "enable_interface":          2,
    "change_dns_server":         5,
}

# Risk weights for action types
RISK_WEIGHTS: dict[str, str] = {
    "flush_dns":                  "low",
    "ping_test":                  "low",
    "traceroute":                 "low",
    "check_firewall":             "low",
    "restart_network_interface":  "high",
    "release_renew_dhcp":         "medium",
    "change_dns_server":          "medium",
    "reset_winsock":              "high",
    "reset_tcp_ip":               "high",
    "disable_interface":          "high",
    "enable_interface":           "medium",
    "restart_service":            "medium",
}


# ── Guards ────────────────────────────────────────────────────────────────────

def check_cooldown(action_type: str) -> tuple[bool, str]:
    """
    Returns (allowed, reason).
    Blocks the action if the same action_type was executed within its cooldown window.
    """
    cooldown_mins = COOLDOWN_MINUTES.get(action_type)
    if cooldown_mins is None:
        return True, "ok"

    recent = get_recent_actions(n=20)
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=cooldown_mins)

    for entry in reversed(recent):
        if entry.get("action_type") != action_type:
            continue
        if entry.get("status") not in ("executed",):
            continue
        try:
            ts = datetime.fromisoformat(entry["timestamp"])
            if ts > cutoff:
                remaining = int((ts + timedelta(minutes=cooldown_mins) - now).total_seconds() / 60)
                reason = (
                    f"Action '{action_type}' is on cooldown. "
                    f"Last executed {int((now - ts).total_seconds() / 60)}m ago. "
                    f"Wait {remaining}m before retrying."
                )
                log.warning(reason)
                return False, reason
        except (KeyError, ValueError):
            continue

    return True, "ok"


def check_session_cap(session_action_count: int) -> tuple[bool, str]:
    """
    Returns (allowed, reason).
    Blocks further actions if the session cap has been reached.
    """
    if session_action_count >= SESSION_ACTION_CAP:
        reason = (
            f"Session action cap of {SESSION_ACTION_CAP} reached. "
            "Start a new session to continue remediation."
        )
        log.warning(reason)
        return False, reason
    return True, "ok"


def get_risk_level(action_type: str) -> str:
    """Returns the risk level for an action type. Defaults to 'medium' if unknown."""
    return RISK_WEIGHTS.get(action_type, "medium")
