"""
main.py
Local debug runner — bypasses MCP, runs the full pipeline directly in the terminal.
Used for development and testing without Claude Desktop.

Simulates what Claude Desktop would do:
  1. observe_network  → get state + context
  2. For each action  → present to user → get approval → execute_action → verify_action
  3. finalise_session → print summary
"""

import json
import sys
from server.orchestrator import observe, execute_action, verify_action, finalise
from utils.logger import get_logger

log = get_logger(__name__)


def _ask_approval(action: dict) -> bool:
    """Stdin-based HIL approval for local debug runs."""
    print(f"\n{'='*60}")
    print(f"  ACTION APPROVAL REQUIRED")
    print(f"{'='*60}")
    print(f"  Action     : {action.get('action_type')}")
    print(f"  Description: {action.get('description', 'N/A')}")
    print(f"  Risk Level : {action.get('risk_level', '?').upper()}")
    print(f"{'='*60}")
    while True:
        try:
            response = input("  Approve? (yes / no): ").strip().lower()
            if response in ("yes", "y"):
                return True
            elif response in ("no", "n"):
                return False
            else:
                print("  Please enter 'yes' or 'no'.")
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            sys.exit(0)


def _decide_actions(plan_context: str, state: dict) -> list[dict]:
    """
    In debug mode, Claude Desktop isn't available to reason over the context.
    So we auto-generate a simple action list based on probe statuses.
    In real MCP usage, Claude Desktop does this reasoning step.
    """
    actions = []
    probes = state.get("probes", {})
    i = 1

    if probes.get("dns", {}).get("status") in ("degraded", "failed"):
        actions.append({
            "action_id": f"action_{i}",
            "action_type": "flush_dns",
            "description": "DNS probe failed — flush cache to force fresh resolution.",
            "params": {},
            "risk_level": "low",
            "requires_rollback": False,
        })
        i += 1

    if probes.get("connectivity", {}).get("status") in ("degraded", "failed"):
        actions.append({
            "action_id": f"action_{i}",
            "action_type": "release_renew_dhcp",
            "description": "Connectivity degraded — release and renew DHCP lease.",
            "params": {},
            "risk_level": "medium",
            "requires_rollback": True,
        })
        i += 1

    if not actions:
        # Network looks healthy — run a ping test to confirm
        actions.append({
            "action_id": f"action_{i}",
            "action_type": "ping_test",
            "description": "Network appears healthy — running ping test to confirm.",
            "params": {"target": "8.8.8.8"},
            "risk_level": "low",
            "requires_rollback": False,
        })

    return actions


if __name__ == "__main__":
    print("\n=== network_medic — local debug mode ===\n")

    # Stage 1: OBSERVE
    print(">>> Stage 1: Observing network state...")
    obs = observe()
    state = obs["state"]
    print(f"    Health   : {state['overall_health']}")
    print(f"    Anomalies: {state['anomalies'] or 'none'}")

    # Stage 2: DECIDE (Claude Desktop does this in MCP mode)
    actions = _decide_actions(obs["plan_context"], state)
    print(f"\n>>> Stage 2: {len(actions)} action(s) proposed by debug planner")

    # Stage 3: EXECUTE + VERIFY per action
    for action in actions:
        approved = _ask_approval(action)
        if not approved:
            print(f"    Skipped: {action['action_type']}")
            continue

        print(f"\n>>> Executing: {action['action_type']}...")
        exec_result = execute_action(action)
        print(f"    Status: {exec_result.get('status')}")
        if exec_result.get("stdout"):
            print(f"    Output: {exec_result['stdout'][:200]}")

        print(f">>> Verifying: {action['action_type']}...")
        verify_result = verify_action(action["action_type"], action["action_id"])
        print(f"    Verdict: {verify_result.get('verdict')}")
        print(f"    Detail : {verify_result.get('detail')}")

    # Stage 4: FINALISE
    print("\n>>> Stage 4: Finalising session...")
    summary = finalise()
    print(f"\n=== SESSION COMPLETE ===")
    print(f"Plan Verdict : {summary['plan_verdict']}")
    print(f"Final Health : {summary['post_state']['overall_health']}")
    print(json.dumps(summary, indent=2, default=str))
