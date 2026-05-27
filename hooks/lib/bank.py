"""Bank ID derivation and mission setup for Cursor hooks."""

import os
import sys

from .state import read_state, write_state

DEFAULT_BANK_NAME = "cursor"
VALID_FIELDS = {"agent", "project", "session", "user"}


def _workspace_root(hook_input: dict) -> str:
    roots = hook_input.get("workspace_roots") or []
    if roots and isinstance(roots, list):
        return roots[0]
    return hook_input.get("cwd", "")


def derive_bank_id(hook_input: dict, config: dict) -> str:
    prefix = config.get("bankIdPrefix", "")

    if not config.get("dynamicBankId", False):
        base = config.get("bankId") or DEFAULT_BANK_NAME
        return f"{prefix}-{base}" if prefix else base

    fields = config.get("dynamicBankGranularity") or ["agent", "project"]
    if not isinstance(fields, list):
        fields = ["agent", "project"]

    workspace = _workspace_root(hook_input)
    session_id = hook_input.get("conversation_id") or hook_input.get("session_id", "")
    agent_name = config.get("agentName", "cursor")
    user_id = os.environ.get("HINDSIGHT_USER_ID", "")

    field_map = {
        "agent": agent_name,
        "project": os.path.basename(workspace) if workspace else "unknown",
        "session": session_id or "unknown",
        "user": user_id or "anonymous",
    }

    for f in fields:
        if f not in VALID_FIELDS:
            print(
                f'[Hindsight] Unknown dynamicBankGranularity field "{f}" — '
                f"valid: {', '.join(sorted(VALID_FIELDS))}",
                file=sys.stderr,
            )

    segments = [field_map.get(f, "unknown") for f in fields]
    base_bank_id = "::".join(segments)
    return f"{prefix}-{base_bank_id}" if prefix else base_bank_id


def ensure_bank_mission(client, bank_id: str, config: dict, debug_fn=None):
    mission = (config.get("bankMission") or "").strip()
    if not mission:
        return

    missions_set = read_state("bank_missions.json", {})
    if bank_id in missions_set:
        return

    try:
        retain_mission = config.get("retainMission")
        client.update_bank_mission(bank_id, mission, retain_mission=retain_mission)
        missions_set[bank_id] = True
        if len(missions_set) > 10000:
            for k in sorted(missions_set.keys())[: len(missions_set) // 2]:
                del missions_set[k]
        write_state("bank_missions.json", missions_set)
        if debug_fn:
            debug_fn(f"Set mission for bank: {bank_id}")
    except Exception as e:
        if debug_fn:
            debug_fn(f"Could not set bank mission for {bank_id}: {e}")
