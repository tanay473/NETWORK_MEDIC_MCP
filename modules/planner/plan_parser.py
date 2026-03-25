"""
modules/planner/plan_parser.py
Validates and normalises the raw JSON output from the LLM.
Uses plan_schema.json to catch malformed plans before they reach the policy engine.
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import validate, ValidationError

from utils.logger import get_logger

log = get_logger(__name__)

_SCHEMA_PATH = Path(__file__).resolve().parent.parent.parent / "schemas" / "plan_schema.json"
_schema: dict | None = None


def _load_schema() -> dict:
    global _schema
    if _schema is None:
        with open(_SCHEMA_PATH, "r", encoding="utf-8") as f:
            _schema = json.load(f)
        log.debug("plan_schema.json loaded")
    return _schema #type: ignore[return-value]


def parse_and_validate(raw: str) -> dict:
    """
    Parse raw LLM output string → validated plan dict.

    Steps:
      1. Strip markdown fences if LLM wrapped output in ```json ... ```
      2. Parse JSON
      3. Validate against plan_schema.json
      4. Inject plan_id and generated_at if missing

    Returns:
        Validated plan dict conforming to plan_schema.json

    Raises:
        ValueError : JSON parse failure or schema validation failure
    """
    # Step 1 — strip fences
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        cleaned = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])
    cleaned = cleaned.strip()

    # Step 2 — parse JSON
    try:
        plan = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        log.error(f"plan_parser: JSON parse failed | {exc}")
        raise ValueError(f"LLM returned invalid JSON: {exc}") from exc

    # Step 3 — inject defaults before validation
    plan.setdefault("plan_id", str(uuid.uuid4()))
    plan.setdefault("generated_at", datetime.now(timezone.utc).isoformat())

    # Inject action_id into each action if missing
    for i, action in enumerate(plan.get("actions", [])):
        action.setdefault("action_id", f"action_{i+1}")
        action.setdefault("requires_rollback", True)

    # Step 4 — validate against schema
    try:
        validate(instance=plan, schema=_load_schema())
    except ValidationError as exc:
        log.error(f"plan_parser: schema validation failed | {exc.message}")
        raise ValueError(f"Plan failed schema validation: {exc.message}") from exc

    log.info(
        f"Plan validated | plan_id={plan['plan_id']} "
        f"actions={len(plan['actions'])} diagnosis={plan['diagnosis'][:80]}"
    )
    return plan
