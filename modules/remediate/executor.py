"""
modules/remediate/executor.py
Safe execution wrapper + Human-in-the-Loop (HIL) approval gate.

This is where every action pauses for user approval before running.
Flow per action:
    policy allows → snapshot → HIL prompt → user approves → run command → log result
                                           → user rejects → log rejection → skip
"""

from utils.logger import get_logger
from utils.os_detector import get_os
from utils.command_runner import run_command
from modules.remediate.actions_map import get_command
from modules.rollback.rollback import snapshot, revert
from memory.store import log_action

log = get_logger(__name__)


def _format_approval_prompt(action: dict, risk_level: str, command: list[str]) -> str:
    """Formats the approval message surfaced to the user via MCP."""
    return (
        f"\n{'='*60}\n"
        f"⚠️  ACTION APPROVAL REQUIRED\n"
        f"{'='*60}\n"
        f"  Action     : {action.get('action_type')}\n"
        f"  Description: {action.get('description', 'N/A')}\n"
        f"  Risk Level : {risk_level.upper()}\n"
        f"  Command    : {' '.join(command)}\n"
        f"{'='*60}\n"
        f"Approve? (yes / no): "
    )


def execute_plan(
    plan: dict,
    policy_results: list[dict],
    approval_callback,
) -> list[dict]:
    """
    Executes approved actions from the plan one by one, with HIL gate per action.

    Args:
        plan             : validated RemediationPlan dict
        policy_results   : per-action policy verdicts from policy_engine.validate_plan()
        approval_callback: callable(prompt: str) -> bool
                           In MCP mode: surfaces prompt to Claude Desktop, returns user decision.
                           In debug mode (main.py): reads from stdin.

    Returns:
        List of execution result dicts (one per action attempted)
    """
    os = get_os()
    plan_id = plan.get("plan_id", "unknown")
    execution_results = []

    # Build a lookup of policy results by action_id
    policy_map = {r["action_id"]: r for r in policy_results}

    for action in plan.get("actions", []):
        action_id   = action.get("action_id")
        action_type = action.get("action_type")
        params      = action.get("params", {})
        risk_level  = action.get("risk_level", "medium")

        policy = policy_map.get(action_id, {})

        # ── Policy blocked ────────────────────────────────────────────────────
        if not policy.get("allowed", False):
            reason = policy.get("reason", "blocked by policy")
            log.warning(f"Skipping {action_type} — {reason}")
            log_action({
                "plan_id":     plan_id,
                "action_id":   action_id,
                "action_type": action_type,
                "status":      "skipped",
                "risk_level":  risk_level,
                "notes":       reason,
                "os":          os.value,
            })
            execution_results.append({
                "action_id":   action_id,
                "action_type": action_type,
                "status":      "skipped",
                "reason":      reason,
            })
            continue

        # ── Build command ─────────────────────────────────────────────────────
        try:
            command = get_command(action_type, os, params)
        except ValueError as exc:
            log.error(f"No command mapping for {action_type} on {os.value}: {exc}")
            log_action({
                "plan_id":     plan_id,
                "action_id":   action_id,
                "action_type": action_type,
                "status":      "failed",
                "risk_level":  risk_level,
                "notes":       str(exc),
                "os":          os.value,
            })
            execution_results.append({
                "action_id":   action_id,
                "action_type": action_type,
                "status":      "failed",
                "reason":      str(exc),
            })
            continue

        # ── HIL approval gate ─────────────────────────────────────────────────
        prompt = _format_approval_prompt(action, risk_level, command)
        approved = approval_callback(prompt)

        if not approved:
            log.info(f"User rejected action: {action_type}")
            log_action({
                "plan_id":     plan_id,
                "action_id":   action_id,
                "action_type": action_type,
                "status":      "rejected",
                "risk_level":  risk_level,
                "approved_by": "user",
                "command_executed": " ".join(command),
                "os":          os.value,
                "notes":       "User rejected at HIL gate",
            })
            execution_results.append({
                "action_id":   action_id,
                "action_type": action_type,
                "status":      "rejected",
                "reason":      "User rejected at approval gate",
            })
            continue

        # ── Snapshot before execution ─────────────────────────────────────────
        snap = None
        if action.get("requires_rollback", True):
            snap = snapshot(action_type, os.value)
            log.debug(f"Snapshot taken before {action_type} | snap_id={snap.get('snap_id')}")

        # ── Execute ───────────────────────────────────────────────────────────
        log.info(f"Executing: {action_type} | command={' '.join(command)}")
        result = run_command(command)

        if result.success:
            status = "executed"
            log.info(f"Action succeeded: {action_type}")
        else:
            status = "failed"
            log.error(
                f"Action failed: {action_type} | "
                f"rc={result.returncode} stderr={result.stderr[:200]}"
            )
            # Auto-revert on failure if snapshot exists
            if snap:
                log.warning(f"Reverting due to failure: {action_type}")
                revert(snap)

        log_action({
            "plan_id":          plan_id,
            "action_id":        action_id,
            "action_type":      action_type,
            "status":           status,
            "risk_level":       risk_level,
            "approved_by":      "user",
            "command_executed": " ".join(command),
            "stdout":           result.stdout[:500],
            "stderr":           result.stderr[:500],
            "returncode":       result.returncode,
            "os":               os.value,
        })

        execution_results.append({
            "action_id":   action_id,
            "action_type": action_type,
            "status":      status,
            "stdout":      result.stdout,
            "stderr":      result.stderr,
            "returncode":  result.returncode,
            "snap":        snap,
        })

    return execution_results
