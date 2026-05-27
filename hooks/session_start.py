#!/usr/bin/env python3
"""sessionStart hook: verify Hindsight MCP is reachable."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.config import debug_log, load_config
from lib.mcp_client import HindsightMcpClient


def main():
    config = load_config()
    if not config.get("autoRecall") and not config.get("autoRetain"):
        return

    try:
        hook_input = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        hook_input = {}

    debug_log(
        config,
        f"sessionStart: {hook_input.get('session_id', hook_input.get('conversation_id', 'unknown'))}",
    )

    try:
        client = HindsightMcpClient(config.get("mcpUrl", "http://localhost:8888/mcp"), timeout=5)
        if client.health_check():
            debug_log(config, "Hindsight MCP reachable")
        else:
            debug_log(config, "Hindsight MCP health check failed")
    except Exception as e:
        debug_log(config, f"Hindsight MCP not available: {e}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[Hindsight] sessionStart error: {e}", file=sys.stderr)
        sys.exit(0)
