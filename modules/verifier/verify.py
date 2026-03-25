"""
modules/verifier/verify.py
Post-action verification — the feedback signal that closes the pipeline loop.

After each action executes, verify() re-runs the relevant probes,
diffs against the pre-action baseline, and returns a verdict:
  - RESOLVED  : the anomaly is gone → report success
  - UNCHANGED : action had no effect → replan
  - DEGRADED  : things got worse     → trigger rollback
"""

from modules.monitor.probes import check_connectivity, check_dns, check_latency
from memory.store import log_action
from utils.logger import get_logger

log = get_logger(__name__)

# Verdict constants
RESOLVED  = "resolved"
UNCHANGED = "unchanged"
DEGRADED  = "degraded"
SKIPPED   = "skipped"

# Which probes to re-run per action type
_ACTION_PROBE_MAP: dict[str, list[str]] = {
    "flush_dns":                  ["dns"],
    "change_dns_server":          ["dns"],
    "restart_network_interface":  ["connectivity", "latency"],
    "release_renew_dhcp":         ["connectivity", "dns"],
    "reset_winsock":              ["connectivity", "dns", "latency"],
    "reset_tcp_ip":               ["connectivity", "dns", "latency"],
    "disable_interface":          ["connectivity"],
    "enable_interface":           ["connectivity", "latency"],
    "ping_test":                  ["latency"],
    "traceroute":                 ["latency"],
    "check_firewall":             ["connectivity"],
    "restart_service":            ["connectivity", "dns"],
}

_STATUS_RANK = {"healthy": 2, "degraded": 1, "failed": 0}


def _run_probes(probe_names: list[str]) -> dict:
    """Runs the specified subset of probes and returns results keyed by probe name."""
    results = {}
    if "connectivity" in probe_names:
        results["connectivity"] = check_connectivity()
    if "dns" in probe_names:
        results["dns"] = check_dns()
    if "latency" in probe_names:
        results["latency"] = check_latency()
    return results


def _compare(before: dict, after: dict, probe_names: list[str]) -> str:
    """
    Compares before/after probe statuses.
    Returns RESOLVED, UNCHANGED, or DEGRADED.
    """
    improvements = 0
    regressions  = 0

    for probe in probe_names:
        before_status = before.get(probe, {}).get("status", "failed")
        after_status  = after.get(probe, {}).get("status", "failed")

        before_rank = _STATUS_RANK.get(before_status, 0)
        after_rank  = _STATUS_RANK.get(after_status, 0)

        if after_rank > before_rank:
            improvements += 1
        elif after_rank < before_rank:
            regressions += 1

    if regressions > 0:
        return DEGRADED
    if improvements > 0:
        return RESOLVED
    return UNCHANGED


def verify(
    action_type: str,
    pre_action_state: dict,
    plan_id: str,
    action_id: str,
) -> dict:
    """
    Runs post-action verification for a single executed action.

    Args:
        action_type      : the action that was just executed
        pre_action_state : SystemState snapshot taken before execution (from collector)
        plan_id          : for logging
        action_id        : for logging

    Returns:
        {
            "verdict"     : "resolved" | "unchanged" | "degraded",
            "probe_results": { probe_name: probe_dict, ... },
            "detail"      : human-readable summary
        }
    """
    probe_names = _ACTION_PROBE_MAP.get(action_type, ["connectivity", "dns", "latency"])
    log.info(f"Verifying action={action_type} | probes={probe_names}")

    # Re-run relevant probes
    after_probes = _run_probes(probe_names)
    before_probes = pre_action_state.get("probes", {})

    verdict = _compare(before_probes, after_probes, probe_names)

    # Build human-readable detail
    detail_parts = []
    for probe in probe_names:
        b = before_probes.get(probe, {}).get("status", "unknown")
        a = after_probes.get(probe, {}).get("status", "unknown")
        detail_parts.append(f"{probe}: {b} → {a}")
    detail = " | ".join(detail_parts)

    log.info(f"Verify verdict: {verdict} | {detail}")

    # Update action log with verify result
    log_action({
        "plan_id":       plan_id,
        "action_id":     action_id,
        "action_type":   action_type,
        "status":        "executed",
        "verify_result": verdict,
        "notes":         detail,
    })

    return {
        "verdict":      verdict,
        "probe_results": after_probes,
        "detail":       detail,
    }


def verify_plan_outcome(verify_results: list[dict]) -> str:
    """
    Aggregates individual action verify results into a plan-level verdict.
    Used by orchestrator to decide whether to report success or escalate.

    Logic:
        any DEGRADED  → DEGRADED
        all RESOLVED  → RESOLVED
        else          → UNCHANGED
    """
    verdicts = [r.get("verdict", UNCHANGED) for r in verify_results]

    if DEGRADED in verdicts:
        return DEGRADED
    if all(v == RESOLVED for v in verdicts):
        return RESOLVED
    return UNCHANGED
