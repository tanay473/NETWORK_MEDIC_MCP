"""
modules/planner/llm_planner.py

In MCP mode (Claude Desktop), planning is done by Claude itself — not by a
separate API call. This module's job is to prepare the structured context
that Claude Desktop needs to reason over and produce a plan.

build_plan_context() is called by mcp_server.py's diagnose_network tool.
The returned context is surfaced to Claude Desktop, which then decides the
plan and calls execute_action per action via subsequent tool calls.
"""

from pathlib import Path
from modules.planner.memory_context import build_memory_block
from utils.logger import get_logger

log = get_logger(__name__)

_PROMPT_PATH = Path(__file__).resolve().parent.parent.parent / "prompts" / "planner_prompt.txt"


def _load_prompt_template() -> str:
    with open(_PROMPT_PATH, "r", encoding="utf-8") as f:
        return f.read()


def build_plan_context(state: dict) -> str:
    """
    Builds the full diagnostic context string from the current SystemState
    and memory history.

    This is returned to Claude Desktop via the get_network_status or
    diagnose_network tool. Claude Desktop uses it to reason about what
    actions to take and calls execute_action for each one.

    Args:
        state: SystemState dict from collector.py

    Returns:
        Formatted prompt string ready for Claude Desktop to reason over.
    """
    log.info(f"Building plan context | health={state.get('overall_health')}")

    template = _load_prompt_template()
    memory_block = build_memory_block()

    context = template.format(
        os=state.get("os", "unknown"),
        overall_health=state.get("overall_health", "unknown"),
        anomalies="\n".join(f"  - {a}" for a in state.get("anomalies", [])) or "  None detected.",
        connectivity_status=state["probes"]["connectivity"]["status"],
        connectivity_details=state["probes"]["connectivity"].get("details", ""),
        dns_status=state["probes"]["dns"]["status"],
        dns_details=state["probes"]["dns"].get("details", ""),
        latency_status=state["probes"]["latency"]["status"],
        latency_details=state["probes"]["latency"].get("details", ""),
        memory_context=memory_block,
    )

    log.debug(f"Plan context built | length={len(context)} chars")
    return context
