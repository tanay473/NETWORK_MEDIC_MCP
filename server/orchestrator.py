"""
server/orchestrator.py
Pipeline stage runners for network_medic.

In MCP mode, Claude Desktop drives the plan — it calls individual stage
functions exposed as MCP tools rather than one monolithic run() function.

Stages exposed to mcp_server.py:
  observe()        → collect state, save to memory, return state + context
  execute_action() → run a single approved action (HIL is the MCP conversation itself)
  verify_action()  → post-action probe diff for a single action
  finalise()       → save post state, return session summary
"""

from modules.monitor.collector import collect
from modules.planner.llm_planner import build_plan_context
from modules.policy.policy_engine import validate_plan, PolicyViolation
from modules.remediate.executor import execute_plan
from modules.verifier.verify import verify, RESOLVED, DEGRADED
from modules.rollback.rollback import snapshot, revert
from memory.store import save_state, log_action, get_recent_actions
from utils.os_detector import assert_supported, get_os
from utils.logger import get_logger

log = get_logger(__name__)

# In-memory session state (one session at a time per server process)
_session: dict = {}


def observe() -> dict:
    """
    Stage 1 — OBSERVE.
    Runs all probes, saves state to memory, builds plan context for Claude Desktop.

    Returns:
        {
            "state"         : SystemState dict,
            "plan_context"  : formatted string Claude Desktop uses to decide the plan,
            "action_history": last 5 actions for Claude to reference,
        }
    """
    assert_supported()
    log.info("Stage: OBSERVE")

    state = collect()
    save_state(state)

    # Cache pre-state for verify stage
    _session["pre_state"] = state
    _session["exec_results"] = []
    _session["verify_results"] = []

    context = build_plan_context(state)

    return {
        "state":          state,
        "plan_context":   context,
        "action_history": get_recent_actions(5),
    }


def execute_action(action: dict) -> dict:
    """
    Stage 2 — EXECUTE a single action.
    Called by Claude Desktop once per action after user approves in conversation.

    HIL is handled naturally by the MCP conversation:
      Claude presents the action → user says yes/no → Claude calls this tool only if approved.

    Args:
        action: single action dict conforming to plan_schema action item structure
                {action_id, action_type, description, params, risk_level, requires_rollback}

    Returns:
        Execution result dict with status, stdout, stderr, snap_id
    """
    log.info(f"Stage: EXECUTE | action_type={action.get('action_type')}")

    os = get_os()
    action_type = action.get("action_type")
    action_id   = action.get("action_id", "unknown")
    params      = action.get("params", {})
    risk_level  = action.get("risk_level", "medium")

    from utils.command_runner import run_command
    from modules.remediate.actions_map import get_command

    # Snapshot before execution
    snap = None
    if action.get("requires_rollback", True):
        snap = snapshot(action_type, os.value, params)#type: ignore

    # Build and run command
    try:
        command = get_command(action_type, os, params)#type: ignore
    except ValueError as exc:
        log.error(f"No command mapping: {exc}")
        log_action({
            "action_type": action_type,
            "action_id":   action_id,
            "status":      "failed",
            "risk_level":  risk_level,
            "os":          os.value,
            "notes":       str(exc),
        })
        return {"action_id": action_id, "action_type": action_type, "status": "failed", "reason": str(exc)}

    result = run_command(command)
    status = "executed" if result.success else "failed"

    # Auto-revert on failure
    if not result.success and snap:
        log.warning(f"Action failed — auto-reverting {action_type}")
        revert(snap)

    log_action({
        "action_type":      action_type,
        "action_id":        action_id,
        "status":           status,
        "risk_level":       risk_level,
        "approved_by":      "user",
        "command_executed": " ".join(command),
        "stdout":           result.stdout[:500],
        "stderr":           result.stderr[:500],
        "returncode":       result.returncode,
        "os":               os.value,
    })

    exec_result = {
        "action_id":   action_id,
        "action_type": action_type,
        "status":      status,
        "stdout":      result.stdout,
        "stderr":      result.stderr,
        "returncode":  result.returncode,
        "snap":        snap,
    }

    _session.setdefault("exec_results", []).append(exec_result)
    return exec_result


def verify_action(action_type: str, action_id: str) -> dict:
    """
    Stage 3 — VERIFY a single executed action.
    Called by Claude Desktop after each execute_action call.

    Returns:
        verify result dict with verdict (resolved/unchanged/degraded) and probe diff.
        If DEGRADED, also triggers rollback automatically.
    """
    log.info(f"Stage: VERIFY | action_type={action_type}")

    pre_state = _session.get("pre_state", {})

    v = verify(
        action_type=action_type,
        pre_action_state=pre_state,
        plan_id=_session.get("plan_id", "unknown"),
        action_id=action_id,
    )
    v["action_id"] = action_id

    # Rollback if degraded
    if v["verdict"] == DEGRADED:
        exec_results = _session.get("exec_results", [])
        snap = next((r.get("snap") for r in exec_results if r.get("action_id") == action_id), None)
        if snap:
            log.warning(f"DEGRADED — rolling back {action_type}")
            revert(snap)

    _session.setdefault("verify_results", []).append(v)
    return v


def finalise() -> dict:
    """
    Stage 4 — LOG + LEARN.
    Called by Claude Desktop after all actions are complete.
    Runs a final probe snapshot and returns session summary for Claude to present.

    Returns:
        {
            "post_state"    : final SystemState,
            "exec_results"  : all execution results,
            "verify_results": all verify results,
            "plan_verdict"  : resolved | unchanged | degraded,
        }
    """
    log.info("Stage: FINALISE")

    from modules.verifier.verify import verify_plan_outcome
    post_state = collect()
    save_state(post_state)

    plan_verdict = verify_plan_outcome(_session.get("verify_results", []))

    return {
        "post_state":     post_state,
        "exec_results":   _session.get("exec_results", []),
        "verify_results": _session.get("verify_results", []),
        "plan_verdict":   plan_verdict,
    }
