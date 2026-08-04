#!/usr/bin/env python3
"""Auto-recall hook for beforeSubmitPrompt (Cursor).

Calls Hindsight via MCP recall and injects memories as additional_context.
"""

import io
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Workspace spill helper (keeps beforeSubmitPrompt context WSL-readable)
_REPO_HOOKS_LIB = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "hooks", "lib")
)
if _REPO_HOOKS_LIB not in sys.path:
    sys.path.insert(0, _REPO_HOOKS_LIB)
from context_spill import emit_additional_context

from lib.bank import derive_bank_id, ensure_bank_mission
from lib.config import debug_log, load_config
from lib.content import (
    compose_recall_query,
    format_current_time,
    format_memories,
    read_transcript,
    strip_user_query_wrapper,
    truncate_recall_query,
)
from lib.mcp_client import HindsightMcpClient
from lib.state import write_state

LAST_RECALL_STATE = "last_recall.json"


def main():
    if sys.platform == "win32":
        sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace")
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

    config = load_config()
    if not config.get("autoRecall"):
        debug_log(config, "Auto-recall disabled")
        return

    try:
        hook_input = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        print("[Hindsight] Failed to read hook input", file=sys.stderr)
        return

    prompt = strip_user_query_wrapper((hook_input.get("prompt") or "").strip())
    if len(prompt) < 5:
        debug_log(config, "Prompt too short for recall")
        return

    def _dbg(*a):
        debug_log(config, *a)

    try:
        client = HindsightMcpClient(
            config.get("mcpUrl", "http://localhost:8888/mcp"),
            timeout=config.get("recallTimeout", 10),
        )
    except ValueError as e:
        print(f"[Hindsight] Invalid MCP URL: {e}", file=sys.stderr)
        return

    bank_id = derive_bank_id(hook_input, config)
    ensure_bank_mission(client, bank_id, config, debug_fn=_dbg)

    recall_context_turns = config.get("recallContextTurns", 1)
    recall_max_query_chars = config.get("recallMaxQueryChars", 800)
    recall_roles = config.get("recallRoles", ["user", "assistant"])

    if recall_context_turns > 1:
        transcript_path = hook_input.get("transcript_path") or os.environ.get("CURSOR_TRANSCRIPT_PATH", "")
        messages = read_transcript(transcript_path)
        query = compose_recall_query(prompt, messages, recall_context_turns, recall_roles)
    else:
        query = prompt

    query = truncate_recall_query(query, prompt, recall_max_query_chars)[:recall_max_query_chars]

    try:
        response = client.recall(
            query=query,
            bank_id=bank_id,
            max_tokens=config.get("recallMaxTokens", 1024),
            budget=config.get("recallBudget", "mid"),
            types=config.get("recallTypes"),
        )
    except Exception as e:
        print(f"[Hindsight] Recall failed: {e}", file=sys.stderr)
        return

    results = response.get("results", [])
    if not results:
        debug_log(config, "No memories found")
        return

    preamble = config.get("recallPromptPreamble", "")
    memories_formatted = format_memories(results)
    context_message = (
        f"<hindsight_memories>\n"
        f"{preamble}\n"
        f"Current time - {format_current_time()}\n\n"
        f"{memories_formatted}\n"
        f"</hindsight_memories>"
    )

    write_state(
        LAST_RECALL_STATE,
        {
            "context": context_message,
            "saved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "bank_id": bank_id,
            "result_count": len(results),
        },
    )

    max_inline_chars = int(config.get("recallMaxInlineChars", 3500))
    emit_additional_context(context_message, "recall", max_inline_chars=max_inline_chars)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[Hindsight] Unexpected error in recall: {e}", file=sys.stderr)
        try:
            sys.exit(2 if load_config().get("debug") else 0)
        except Exception:
            sys.exit(0)
