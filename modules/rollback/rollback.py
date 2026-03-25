"""
modules/rollback/rollback.py
Snapshot-before, revert-after — single file for the full rollback lifecycle.

snapshot() : called by executor.py before every high/medium risk action
revert()   : called by executor.py on action failure, or by orchestrator on DEGRADED verdict
log()      : writes rollback event to memory/data/rollback_log.json
"""

import uuid
from datetime import datetime, timezone

from utils.command_runner import run_command
from utils.os_detector import get_os, OS
from memory.store import log_rollback
from utils.logger import get_logger

log = get_logger(__name__)


# ── Revert map ────────────────────────────────────────────────────────────────
# Maps action_type → revert command builder per OS.
# Only actions that have a meaningful revert are listed.
# Actions without a revert (e.g. ping_test) are no-ops.

def _get_revert_command(action_type: str, os: OS, snap: dict) -> list[str] | None:
    """
    Returns the revert command for a given action on a given OS.
    Returns None if no revert is available for this action/OS combo.
    """
    params = snap.get("params", {})

    revert_map = {
        # flush_dns — no meaningful revert (cache just repopulates)
        "flush_dns": None,

        # restart_network_interface
        ("restart_network_interface", OS.WINDOWS): ["netsh", "interface", "set", "interface",
                                                     params.get("interface", "Ethernet"), "enable"],
        ("restart_network_interface", OS.LINUX):   ["systemctl", "restart", "NetworkManager"],
        ("restart_network_interface", OS.MAC):     ["ifconfig", params.get("interface", "en0"), "up"],

        # release_renew_dhcp — renew to restore
        ("release_renew_dhcp", OS.WINDOWS): ["ipconfig", "/renew"],
        ("release_renew_dhcp", OS.LINUX):   ["dhclient", params.get("interface", "eth0")],
        ("release_renew_dhcp", OS.MAC):     ["ipconfig", "set", params.get("interface", "en0"), "DHCP"],

        # change_dns_server — restore previous DNS
        ("change_dns_server", OS.WINDOWS): ["netsh", "interface", "ip", "set", "dns",
                                             params.get("interface", "Ethernet"), "dhcp"],
        ("change_dns_server", OS.LINUX):   ["resolvectl", "revert",
                                             params.get("interface", "eth0")],
        ("change_dns_server", OS.MAC):     ["networksetup", "-setdnsservers",
                                             params.get("interface", "Wi-Fi"), "empty"],

        # disable_interface → re-enable
        ("disable_interface", OS.WINDOWS): ["netsh", "interface", "set", "interface",
                                             params.get("interface", "Ethernet"), "enable"],
        ("disable_interface", OS.LINUX):   ["ip", "link", "set",
                                             params.get("interface", "eth0"), "up"],
        ("disable_interface", OS.MAC):     ["ifconfig", params.get("interface", "en0"), "up"],

        # reset_winsock / reset_tcp_ip — no command-level revert; flag for manual review
        "reset_winsock": None,
        "reset_tcp_ip":  None,
    }

    # Try (action_type, os) tuple first, then bare action_type
    cmd = revert_map.get((action_type, os), revert_map.get(action_type, "NOT_FOUND"))

    if cmd == "NOT_FOUND":
        return None  # No revert defined — treated as no-op
    return cmd


# ── Public API ────────────────────────────────────────────────────────────────

def snapshot(action_type: str, os_value: str, params: dict | None = None) -> dict:
    """
    Records a pre-action snapshot.
    Returns a snap dict that must be passed to revert() if needed.

    Args:
        action_type : the action about to be executed
        os_value    : string OS identifier (from get_os().value)
        params      : action params (interface name, dns server, etc.)

    Returns:
        snap dict with snap_id, action_type, os, params, timestamp
    """
    snap = {
        "snap_id":     str(uuid.uuid4()),
        "action_type": action_type,
        "os":          os_value,
        "params":      params or {},
        "timestamp":   datetime.now(timezone.utc).isoformat(),
    }
    log.debug(f"Snapshot recorded | snap_id={snap['snap_id']} action={action_type}")
    return snap


def revert(snap: dict) -> dict:
    """
    Attempts to revert the action described in the snapshot.

    Args:
        snap: the dict returned by snapshot()

    Returns:
        {
            "snap_id"    : str,
            "action_type": str,
            "result"     : "reverted" | "no_revert_available" | "revert_failed",
            "detail"     : str,
        }
    """
    action_type = snap.get("action_type", "unknown")
    os = get_os()
    snap_id = snap.get("snap_id", "?")

    log.warning(f"Reverting action={action_type} | snap_id={snap_id}")

    revert_cmd = _get_revert_command(action_type, os, snap)

    if revert_cmd is None:
        detail = f"No revert command available for '{action_type}' on {os.value}. Manual review required."
        log.warning(detail)
        result = "no_revert_available"
    else:
        cmd_result = run_command(revert_cmd)
        if cmd_result.success:
            detail = f"Revert succeeded | cmd={' '.join(revert_cmd)}"
            result = "reverted"
            log.info(detail)
        else:
            detail = (
                f"Revert failed | cmd={' '.join(revert_cmd)} "
                f"rc={cmd_result.returncode} err={cmd_result.stderr[:200]}"
            )
            result = "revert_failed"
            log.error(detail)

    rollback_entry = {
        "snap_id":     snap_id,
        "action_type": action_type,
        "os":          os.value,
        "result":      result,
        "detail":      detail,
        "timestamp":   datetime.now(timezone.utc).isoformat(),
    }
    log_rollback(rollback_entry)

    return rollback_entry
