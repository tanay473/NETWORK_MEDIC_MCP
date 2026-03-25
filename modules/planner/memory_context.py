"""
modules/planner/memory_context.py
Builds the memory context block injected into the planner prompt.
Pulls recent action history and state snapshots from memory/store.py
so the LLM can reason about what has already been tried.
"""

from memory.store import get_recent_actions, get_state_history
from utils.logger import get_logger

log = get_logger(__name__)

_MAX_ACTIONS  = 5   # last N actions shown to planner
_MAX_STATES   = 3   # last N state snapshots shown to planner


def build_memory_block() -> str:
    """
    Returns a formatted string summarising recent history.
    Injected into planner_prompt.txt as {memory_context}.

    Format:
        ## Recent Actions
        [action_type] | status | verify_result | risk_level

        ## Recent Network States
        [timestamp] overall_health | anomalies
    """
    lines = []

    # ── Recent actions ────────────────────────────────────────────────────────
    recent_actions = get_recent_actions(_MAX_ACTIONS)
    lines.append("## Recent Actions (last {n})".format(n=len(recent_actions)))

    if not recent_actions:
        lines.append("No prior actions recorded.")
    else:
        for a in recent_actions:
            lines.append(
                f"  - [{a.get('timestamp', '?')}] "
                f"action={a.get('action_type', '?')} | "
                f"status={a.get('status', '?')} | "
                f"verify={a.get('verify_result', 'skipped')} | "
                f"risk={a.get('risk_level', '?')}"
            )

    lines.append("")

    # ── Recent states ─────────────────────────────────────────────────────────
    recent_states = get_state_history(_MAX_STATES)
    lines.append("## Recent Network States (last {n})".format(n=len(recent_states)))

    if not recent_states:
        lines.append("No prior state snapshots available.")
    else:
        for s in recent_states:
            anomalies = s.get("anomalies", [])
            anomaly_str = "; ".join(anomalies) if anomalies else "none"
            lines.append(
                f"  - [{s.get('timestamp', '?')}] "
                f"health={s.get('overall_health', '?')} | "
                f"anomalies: {anomaly_str}"
            )

    context = "\n".join(lines)
    log.debug(f"Memory context built | actions={len(recent_actions)} states={len(recent_states)}")
    return context
