#!/usr/bin/env python3
"""Auto-retain hook for stop (Cursor).

Reads the session transcript and stores it via MCP retain.
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.bank import derive_bank_id, ensure_bank_mission
from lib.config import debug_log, load_config
from lib.content import (
    prepare_retention_transcript,
    read_transcript,
    slice_last_turns_by_user_boundary,
)
from lib.mcp_client import HindsightMcpClient
from lib.state import increment_turn_count


def main():
    config = load_config()
    if not config.get("autoRetain"):
        debug_log(config, "Auto-retain disabled")
        return

    try:
        hook_input = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        print("[Hindsight] Failed to read hook input", file=sys.stderr)
        return

    session_id = hook_input.get("conversation_id") or hook_input.get("session_id", "unknown")
    transcript_path = hook_input.get("transcript_path") or os.environ.get("CURSOR_TRANSCRIPT_PATH", "")

    include_tool_calls = config.get("retainToolCalls", True)
    all_messages = read_transcript(transcript_path, include_tool_calls=include_tool_calls)
    if not all_messages:
        debug_log(config, "No messages in transcript, skipping retain")
        return

    retain_every_n = max(1, config.get("retainEveryNTurns", 1))
    retain_mode = config.get("retainMode", "full-session")
    messages_to_retain = all_messages
    retain_full_window = True

    if retain_every_n > 1:
        turn_count = increment_turn_count(session_id)
        if turn_count % retain_every_n != 0:
            debug_log(config, f"Turn {turn_count}/{retain_every_n}, skipping retain")
            return

    if retain_mode == "chunked" and retain_every_n > 1:
        overlap = config.get("retainOverlapTurns", 0)
        window = retain_every_n + overlap
        messages_to_retain = slice_last_turns_by_user_boundary(all_messages, window)
        debug_log(config, f"Chunked retain: {len(messages_to_retain)} messages")
    else:
        debug_log(config, f"Full session retain: {len(all_messages)} messages")

    retain_roles = config.get("retainRoles", ["user", "assistant"])
    transcript, message_count = prepare_retention_transcript(
        messages_to_retain,
        retain_roles,
        retain_full_window,
        include_tool_calls=include_tool_calls,
    )
    if not transcript:
        debug_log(config, "Empty transcript after formatting")
        return

    def _dbg(*a):
        debug_log(config, *a)

    try:
        client = HindsightMcpClient(config.get("mcpUrl", "http://localhost:8888/mcp"))
    except ValueError as e:
        print(f"[Hindsight] Invalid MCP URL: {e}", file=sys.stderr)
        return

    bank_id = derive_bank_id(hook_input, config)
    ensure_bank_mission(client, bank_id, config, debug_fn=_dbg)

    if retain_mode == "chunked" and retain_every_n > 1:
        document_id = f"{session_id}-{int(time.time() * 1000)}"
    else:
        document_id = session_id

    template_vars = {
        "session_id": session_id,
        "bank_id": bank_id,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    def resolve_template(value: str) -> str:
        for k, v in template_vars.items():
            value = value.replace(f"{{{k}}}", v)
        return value

    raw_tags = config.get("retainTags", [])
    tags = [resolve_template(t) for t in raw_tags] if raw_tags else None

    metadata = {
        "retained_at": template_vars["timestamp"],
        "message_count": str(message_count),
        "session_id": session_id,
    }
    for k, v in config.get("retainMetadata", {}).items():
        metadata[k] = resolve_template(str(v))

    debug_log(
        config,
        f"Retaining to bank '{bank_id}', doc '{document_id}', {message_count} messages",
    )

    try:
        client.retain(
            content=transcript,
            bank_id=bank_id,
            document_id=document_id,
            context=config.get("retainContext", "cursor"),
            metadata=metadata,
            tags=tags,
        )
    except Exception as e:
        print(f"[Hindsight] Retain failed: {e}", file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[Hindsight] Unexpected error in retain: {e}", file=sys.stderr)
        try:
            sys.exit(2 if load_config().get("debug") else 0)
        except Exception:
            sys.exit(0)
