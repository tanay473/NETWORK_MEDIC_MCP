"""
utils/permissions.py
Checks whether the process has sufficient privileges for a given action.
Called by policy engine before execution — catches permission issues early
instead of letting commands fail mid-run.
"""

import os
import sys

from utils.logger import get_logger

log = get_logger(__name__)


def is_admin() -> bool:
    """
    Returns True if the current process has admin/root privileges.
    - Windows : checks for Administrator token
    - Linux/Mac: checks for uid == 0
    """
    try:
        if sys.platform == "win32":
            import ctypes
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        else:
            return os.geteuid() == 0
    except Exception as exc:
        log.warning(f"Could not determine admin status: {exc}")
        return False


# Actions that require elevated privileges
_PRIVILEGED_ACTIONS: set[str] = {
    "restart_network_interface",
    "flush_dns",
    "release_renew_dhcp",
    "change_dns_server",
    "reset_winsock",
    "reset_tcp_ip",
    "disable_interface",
    "enable_interface",
}


def requires_admin(action_type: str) -> bool:
    """Returns True if the given action type needs admin/root to execute."""
    return action_type in _PRIVILEGED_ACTIONS


def check_permission(action_type: str) -> tuple[bool, str]:
    """
    Validates whether the current process can execute the given action.

    Returns:
        (allowed: bool, reason: str)

    Usage:
        allowed, reason = check_permission("flush_dns")
        if not allowed:
            # surface reason to user / policy engine
    """
    if requires_admin(action_type) and not is_admin():
        reason = (
            f"Action '{action_type}' requires administrator/root privileges. "
            "Please restart network_medic with elevated permissions."
        )
        log.warning(reason)
        return False, reason

    return True, "ok"
