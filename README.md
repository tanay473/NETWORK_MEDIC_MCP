# network_medic

An autonomous network monitoring and auto-remediation MCP server for Claude Desktop.

Claude Desktop acts as the LLM brain — it observes the network state, decides the remediation plan, presents each action to the user for approval, executes, verifies, and summarises the session.

No separate Anthropic API key required.

---

## Architecture

```
Observe → Plan (Claude Desktop) → Policy Validation → Human Approval → Execute → Verify → Log + Learn
```

### MCP Tools

| Tool | Description |
|---|---|
| `observe_network` | Runs probes (connectivity, DNS, latency), returns state + diagnostic context |
| `execute_action` | Executes a single approved action |
| `verify_action` | Post-action probe diff — returns resolved / unchanged / degraded |
| `finalise_session` | Saves final state, returns session summary |
| `get_action_history` | View recent action log |
| `submit_feedback` | Rate the session outcome |

---

## Project Structure

```
server/          MCP entry point + pipeline stage functions
modules/
  monitor/       Observe — connectivity, DNS, latency probes
  planner/       Context builder — prompt + memory injection
  policy/        Safety — conflict checks, cooldowns, risk caps
  remediate/     Execute — HIL gate, OS-specific commands
  verifier/      Verify — post-action probe diff
  rollback/      Recover — snapshot + revert
memory/          Persistent state — action log, state history, feedback
prompts/         LLM prompt templates
schemas/         JSON Schema contracts
utils/           Shared infrastructure
```

---

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/your-username/network_medic.git
cd network_medic
```

### 2. Create a virtual environment and install dependencies

```bash
python -m venv venv

# Windows
venv\Scripts\python.exe -m pip install -r requirements.txt

# Linux / macOS
source venv/bin/activate && pip install -r requirements.txt
```

### 3. Wire into Claude Desktop

Add to `%APPDATA%\Claude\claude_desktop_config.json` (Windows) or `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS):

```json
{
  "mcpServers": {
    "network-medic": {
      "command": "C:/path/to/network_medic/venv/Scripts/python.exe",
      "args": ["C:/path/to/network_medic/server/mcp_server.py"],
      "cwd": "C:/path/to/network_medic"
    }
  }
}
```

Replace `C:/path/to/network_medic` with your actual clone path.

Restart Claude Desktop after saving the config.

---

## Local Debug Run

Runs the full pipeline in the terminal without Claude Desktop:

```bash
python main.py
```

---

## Supported Platforms

- Windows
- Linux
- macOS

---

## Requirements

- Python 3.13+
- Claude Desktop
