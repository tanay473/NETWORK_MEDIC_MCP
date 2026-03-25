"""
server/mcp_server.py
MCP server entry point for network_medic.

Claude Desktop is the LLM brain — it receives network state, decides the plan,
and calls tools per action. No separate Anthropic API key needed.

Tools exposed:
  - observe_network    : full probe run — connectivity, DNS, latency + device state
  - check_device_state : targeted device state probes — gateway, interfaces, ports, wifi
  - execute_action     : executes a single approved action
  - verify_action      : post-action probe diff
  - finalise_session   : saves post-state, returns session summary
  - get_action_history : returns recent action log
  - submit_feedback    : lets user rate the session
"""

import sys
import json
import asyncio
from pathlib import Path

# ── Ensure project root is on sys.path ────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
# ─────────────────────────────────────────────────────────────────────────────

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

from server.orchestrator import observe, execute_action, verify_action, finalise
from modules.monitor.probes import check_gateway, check_interfaces, check_ports, check_wifi
from memory.store import save_feedback, get_recent_actions
from utils.logger import get_logger

log = get_logger(__name__)

app = Server("network-medic")


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="observe_network",
            description=(
                "Run all network probes — connectivity, DNS, latency, gateway, interfaces, "
                "ports, and WiFi state. Returns the complete system state with anomalies and "
                "action history. Use this first to understand what is wrong before deciding actions."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        types.Tool(
            name="check_device_state",
            description=(
                "Run targeted device-level probes to inspect the local machine's network state. "
                "Checks: default gateway reachability, network interface up/down status, "
                "critical port availability (53/80/443), and WiFi/Ethernet connection info. "
                "Use this when you need device-level detail without running the full observe cycle."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "probes": {
                        "type": "array",
                        "description": "Which probes to run. Omit to run all four.",
                        "items": {
                            "type": "string",
                            "enum": ["gateway", "interfaces", "ports", "wifi"],
                        },
                    }
                },
                "required": [],
            },
        ),
        types.Tool(
            name="execute_action",
            description=(
                "Execute a single remediation action. Only call this after presenting the action "
                "to the user and receiving their explicit approval in the conversation."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "object",
                        "description": "Single action object with action_id, action_type, description, params, risk_level, requires_rollback",
                        "properties": {
                            "action_id":         {"type": "string"},
                            "action_type":       {"type": "string"},
                            "description":       {"type": "string"},
                            "params":            {"type": "object"},
                            "risk_level":        {"type": "string", "enum": ["low", "medium", "high"]},
                            "requires_rollback": {"type": "boolean"},
                        },
                        "required": ["action_id", "action_type", "description", "risk_level"],
                    }
                },
                "required": ["action"],
            },
        ),
        types.Tool(
            name="verify_action",
            description=(
                "Run post-action verification after an execute_action call. "
                "Re-runs the relevant probes and returns a verdict: "
                "resolved (fixed), unchanged (no effect), or degraded (got worse — triggers rollback)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "action_type": {"type": "string", "description": "The action_type just executed"},
                    "action_id":   {"type": "string", "description": "The action_id just executed"},
                },
                "required": ["action_type", "action_id"],
            },
        ),
        types.Tool(
            name="finalise_session",
            description=(
                "Call this after all actions are complete. "
                "Saves the final network state, computes the overall session verdict, "
                "and returns a summary to present to the user."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        types.Tool(
            name="get_action_history",
            description="Retrieve the last N actions taken by network_medic across all sessions.",
            inputSchema={
                "type": "object",
                "properties": {
                    "n": {"type": "integer", "description": "Number of recent actions to return (default: 10)", "default": 10}
                },
                "required": [],
            },
        ),
        types.Tool(
            name="submit_feedback",
            description="Submit user feedback on a completed remediation session.",
            inputSchema={
                "type": "object",
                "properties": {
                    "plan_id":  {"type": "string", "description": "The plan_id from the session being rated"},
                    "feedback": {"type": "string", "enum": ["helpful", "not_helpful", "neutral"]},
                    "notes":    {"type": "string", "description": "Optional comments"},
                },
                "required": ["plan_id", "feedback"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:

    # ── observe_network ───────────────────────────────────────────────────────
    if name == "observe_network":
        log.info("MCP tool called: observe_network")
        try:
            result = await asyncio.get_event_loop().run_in_executor(None, observe)
            return [types.TextContent(type="text", text=json.dumps(result, indent=2, default=str))]
        except Exception as exc:
            log.error(f"observe_network failed: {exc}")
            return [types.TextContent(type="text", text=f"Error: {exc}")]

    # ── check_device_state ────────────────────────────────────────────────────
    elif name == "check_device_state":
        log.info("MCP tool called: check_device_state")
        try:
            probe_map = {
                "gateway":    check_gateway,
                "interfaces": check_interfaces,
                "ports":      check_ports,
                "wifi":       check_wifi,
            }
            requested = arguments.get("probes") or list(probe_map.keys())
            results = {}

            def run_probes():
                for probe_name in requested:
                    if probe_name in probe_map:
                        results[probe_name] = probe_map[probe_name]()
                return results

            data = await asyncio.get_event_loop().run_in_executor(None, run_probes)
            return [types.TextContent(type="text", text=json.dumps(data, indent=2, default=str))]
        except Exception as exc:
            log.error(f"check_device_state failed: {exc}")
            return [types.TextContent(type="text", text=f"Error: {exc}")]

    # ── execute_action ────────────────────────────────────────────────────────
    elif name == "execute_action":
        log.info(f"MCP tool called: execute_action | {arguments.get('action', {}).get('action_type')}")
        try:
            action = arguments.get("action", {})
            result = await asyncio.get_event_loop().run_in_executor(
                None, lambda: execute_action(action)
            )
            return [types.TextContent(type="text", text=json.dumps(result, indent=2, default=str))]
        except Exception as exc:
            log.error(f"execute_action failed: {exc}")
            return [types.TextContent(type="text", text=f"Error: {exc}")]

    # ── verify_action ─────────────────────────────────────────────────────────
    elif name == "verify_action":
        log.info(f"MCP tool called: verify_action | {arguments.get('action_type')}")
        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: verify_action(
                    action_type=arguments["action_type"],
                    action_id=arguments["action_id"],
                ),
            )
            return [types.TextContent(type="text", text=json.dumps(result, indent=2, default=str))]
        except Exception as exc:
            log.error(f"verify_action failed: {exc}")
            return [types.TextContent(type="text", text=f"Error: {exc}")]

    # ── finalise_session ──────────────────────────────────────────────────────
    elif name == "finalise_session":
        log.info("MCP tool called: finalise_session")
        try:
            result = await asyncio.get_event_loop().run_in_executor(None, finalise)
            return [types.TextContent(type="text", text=json.dumps(result, indent=2, default=str))]
        except Exception as exc:
            log.error(f"finalise_session failed: {exc}")
            return [types.TextContent(type="text", text=f"Error: {exc}")]

    # ── get_action_history ────────────────────────────────────────────────────
    elif name == "get_action_history":
        n = arguments.get("n", 10)
        history = get_recent_actions(n)
        return [types.TextContent(type="text", text=json.dumps(history, indent=2, default=str))]

    # ── submit_feedback ───────────────────────────────────────────────────────
    elif name == "submit_feedback":
        save_feedback(
            plan_id=arguments.get("plan_id", "unknown"),
            feedback=arguments.get("feedback", "neutral"),
            notes=arguments.get("notes", ""),
        )
        return [types.TextContent(type="text", text=f"Feedback recorded: {arguments.get('feedback')}")]

    else:
        return [types.TextContent(type="text", text=f"Unknown tool: {name}")]


# ── Entry point ───────────────────────────────────────────────────────────────

async def main():
    log.info("network-medic MCP server starting...")
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
