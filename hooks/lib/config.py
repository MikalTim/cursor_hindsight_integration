"""Configuration for Hindsight Cursor hooks."""

import json
import os
import sys

DEFAULTS = {
    "mcpUrl": "http://localhost:8888/mcp",
    "bankId": "cursor",
    "bankMission": (
        "You are a Cursor AI coding assistant. Focus on technical decisions, "
        "code changes, debugging sessions, and project context relevant to the user's work."
    ),
    "retainMission": (
        "Extract technical decisions, code patterns, debugging solutions, user preferences, "
        "project context, and architectural choices. Ignore routine greetings and transient details."
    ),
    "autoRecall": True,
    "autoRetain": True,
    "retainMode": "full-session",
    "recallBudget": "mid",
    "recallMaxTokens": 1024,
    "recallTimeout": 10,
    "recallTypes": None,
    "recallContextTurns": 1,
    "recallMaxQueryChars": 800,
    "recallRoles": ["user", "assistant"],
    "recallPromptPreamble": (
        "Relevant memories from past conversations (prioritize recent when conflicting). "
        "Only use memories that are directly useful to continue this conversation; ignore the rest:"
    ),
    "retainRoles": ["user", "assistant"],
    "retainEveryNTurns": 10,
    "retainOverlapTurns": 2,
    "retainContext": "cursor",
    "retainTags": ["{session_id}"],
    "retainMetadata": {},
    "retainToolCalls": True,
    "bankIdPrefix": "",
    "dynamicBankId": False,
    "dynamicBankGranularity": ["agent", "project"],
    "agentName": "cursor",
    "debug": False,
}

ENV_OVERRIDES = {
    "HINDSIGHT_MCP_URL": ("mcpUrl", str),
    "HINDSIGHT_BANK_ID": ("bankId", str),
    "HINDSIGHT_AGENT_NAME": ("agentName", str),
    "HINDSIGHT_AUTO_RECALL": ("autoRecall", bool),
    "HINDSIGHT_AUTO_RETAIN": ("autoRetain", bool),
    "HINDSIGHT_RETAIN_MODE": ("retainMode", str),
    "HINDSIGHT_RECALL_BUDGET": ("recallBudget", str),
    "HINDSIGHT_RECALL_MAX_TOKENS": ("recallMaxTokens", int),
    "HINDSIGHT_RECALL_TIMEOUT": ("recallTimeout", int),
    "HINDSIGHT_RECALL_MAX_QUERY_CHARS": ("recallMaxQueryChars", int),
    "HINDSIGHT_RECALL_CONTEXT_TURNS": ("recallContextTurns", int),
    "HINDSIGHT_DYNAMIC_BANK_ID": ("dynamicBankId", bool),
    "HINDSIGHT_BANK_MISSION": ("bankMission", str),
    "HINDSIGHT_DEBUG": ("debug", bool),
}


def _cast_env(value: str, typ):
    try:
        if typ is bool:
            return value.lower() in ("true", "1", "yes")
        if typ is int:
            return int(value)
        return value
    except (ValueError, AttributeError):
        return None


def _load_settings_file(path: str, config: dict) -> None:
    if not os.path.exists(path):
        return
    try:
        with open(path) as f:
            file_config = json.load(f)
        config.update({k: v for k, v in file_config.items() if v is not None})
    except (json.JSONDecodeError, OSError) as e:
        debug_log(config, f"Failed to load {path}: {e}")


def load_config() -> dict:
    """Load config: defaults → plugin settings.json → ~/.hindsight/cursor.json → env."""
    config = dict(DEFAULTS)
    install_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _load_settings_file(os.path.join(install_root, "settings.json"), config)
    user_config = os.path.join(os.path.expanduser("~"), ".hindsight", "cursor.json")
    _load_settings_file(user_config, config)

    for env_name, (key, typ) in ENV_OVERRIDES.items():
        val = os.environ.get(env_name)
        if val is not None:
            cast_val = _cast_env(val, typ)
            if cast_val is not None:
                config[key] = cast_val

    return config


def debug_log(config: dict, *args):
    if config.get("debug"):
        print("[Hindsight]", *args, file=sys.stderr)
