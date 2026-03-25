"""
modules/policy/policy_engine.py
Validates the full remediation plan before any action reaches the HIL gate.
Checks for conflicts, redundancy, and unsupported action types.
Also runs per-action checks: permission, cooldown, session cap.
"""

from modules.policy.action_guard import check_cooldown, check_session_cap, get_risk_level
from utils.permissions import check_permission
from utils.logger import get_logger

log = get_logger(__name__)

# Actions that conflict with each other (cannot both appear in one plan)
_CONFLICTING_PAIRS: list[tuple[str, str]] = [
    ("disable_interface", "restart_network_interface"),
    ("disable_interface", "release_renew_dhcp"),
    ("reset_winsock",     "reset_tcp_ip"),  # redundant and risky together
]

# Known valid action types (must match plan_schema.json enum)
_VALID_ACTION_TYPES: set[str] = {
    "flush_dns", "restart_network_interface", "release_renew_dhcp",
    "change_dns_server", "reset_winsock", "reset_tcp_ip",
    "disable_interface", "enable_interface", "ping_test",
    "traceroute", "check_firewall", "restart_service",
}


class PolicyViolation(Exception):
    """Raised when a plan or action fails policy checks."""
    pass


def validate_plan(plan: dict, session_action_count: int = 0) -> list[dict]:
    """
    Validates the full plan. Returns a list of policy results per action.

    Each result dict:
        {
            "action_id"   : str,
            "action_type" : str,
            "allowed"     : bool,
            "reason"      : str,
            "risk_level"  : str,
        }

    Raises PolicyViolation if a plan-level conflict is detected.
    """
    actions = plan.get("actions", [])
    action_types = [a.get("action_type") for a in actions]

    # ── Plan-level: conflict check ────────────────────────────────────────────
    for a, b in _CONFLICTING_PAIRS:
        if a in action_types and b in action_types:
            raise PolicyViolation(
                f"Conflicting actions in plan: '{a}' and '{b}' cannot both be present."
            )

    # ── Plan-level: redundancy check ─────────────────────────────────────────
    seen = set()
    for at in action_types:
        if at in seen:
            raise PolicyViolation(
                f"Redundant action detected: '{at}' appears more than once in the plan."
            )
        seen.add(at)

    # ── Per-action checks ─────────────────────────────────────────────────────
    results = []
    for action in actions:
        action_type = action.get("action_type", "")
        action_id   = action.get("action_id", "?")

        # Unknown action type
        if action_type not in _VALID_ACTION_TYPES:
            results.append({
                "action_id":   action_id,
                "action_type": action_type,
                "allowed":     False,
                "reason":      f"Unknown action type: '{action_type}'",
                "risk_level":  "high",
            })
            continue

        # Permission check
        perm_ok, perm_reason = check_permission(action_type)
        if not perm_ok:
            results.append({
                "action_id":   action_id,
                "action_type": action_type,
                "allowed":     False,
                "reason":      perm_reason,
                "risk_level":  get_risk_level(action_type),
            })
            continue

        # Cooldown check
        cooldown_ok, cooldown_reason = check_cooldown(action_type)
        if not cooldown_ok:
            results.append({
                "action_id":   action_id,
                "action_type": action_type,
                "allowed":     False,
                "reason":      cooldown_reason,
                "risk_level":  get_risk_level(action_type),
            })
            continue

        # Session cap check
        cap_ok, cap_reason = check_session_cap(session_action_count)
        if not cap_ok:
            results.append({
                "action_id":   action_id,
                "action_type": action_type,
                "allowed":     False,
                "reason":      cap_reason,
                "risk_level":  get_risk_level(action_type),
            })
            continue

        results.append({
            "action_id":   action_id,
            "action_type": action_type,
            "allowed":     True,
            "reason":      "ok",
            "risk_level":  get_risk_level(action_type),
        })
        session_action_count += 1

    allowed_count = sum(1 for r in results if r["allowed"])
    log.info(
        f"Policy validation complete | "
        f"{allowed_count}/{len(results)} actions allowed"
    )
    return results
