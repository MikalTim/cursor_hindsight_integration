"""Transcript parsing and formatting for Cursor Hindsight hooks."""

import json
import os
import re
from datetime import datetime, timezone

_MAX_TOOL_OUTPUT_CHARS = 2000


def strip_memory_tags(content: str) -> str:
    content = re.sub(r"<hindsight_memories>[\s\S]*?</hindsight_memories>", "", content)
    content = re.sub(r"<relevant_memories>[\s\S]*?</relevant_memories>", "", content)
    return content


def strip_user_query_wrapper(content: str) -> str:
    """Remove Cursor <user_query> wrapper from prompt text."""
    content = re.sub(r"</?user_query>", "", content, flags=re.IGNORECASE)
    return content.strip()


def read_transcript(transcript_path: str, include_tool_calls: bool = False) -> list:
    if not transcript_path or not os.path.isfile(transcript_path):
        return []
    if include_tool_calls:
        return _read_cursor_rich(transcript_path)
    return _read_cursor_text(transcript_path)


def _extract_text_blocks(content_blocks: list) -> str:
    parts = []
    for block in content_blocks:
        if isinstance(block, dict) and block.get("type") == "text":
            t = block.get("text", "").strip()
            if t:
                parts.append(strip_user_query_wrapper(strip_memory_tags(t)))
    return "\n".join(p for p in parts if p).strip()


def _read_cursor_text(transcript_path: str) -> list:
    messages = []
    try:
        with open(transcript_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                role = entry.get("role")
                if role not in ("user", "assistant"):
                    continue

                content = entry.get("content")
                if content is None and isinstance(entry.get("message"), dict):
                    content = entry["message"].get("content")

                if isinstance(content, str):
                    text = strip_user_query_wrapper(strip_memory_tags(content))
                elif isinstance(content, list):
                    text = _extract_text_blocks(content)
                else:
                    continue

                if text:
                    messages.append({"role": role, "content": text})
    except OSError:
        pass
    return messages


def _read_cursor_rich(transcript_path: str) -> list:
    messages = []
    assistant_blocks = []

    def flush_assistant():
        nonlocal assistant_blocks
        if assistant_blocks:
            messages.append({"role": "assistant", "content": assistant_blocks})
            assistant_blocks = []

    try:
        with open(transcript_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                role = entry.get("role")
                if role not in ("user", "assistant"):
                    continue

                content = entry.get("content")
                if content is None and isinstance(entry.get("message"), dict):
                    content = entry["message"].get("content")

                if role == "user":
                    flush_assistant()
                    if isinstance(content, str):
                        text = strip_user_query_wrapper(strip_memory_tags(content))
                        blocks = [{"type": "text", "text": text}] if text else []
                    elif isinstance(content, list):
                        blocks = _strip_blocks(content)
                    else:
                        continue
                    if blocks:
                        messages.append({"role": "user", "content": blocks})
                elif role == "assistant":
                    if isinstance(content, str):
                        text = strip_memory_tags(content)
                        if text:
                            assistant_blocks.append({"type": "text", "text": text})
                    elif isinstance(content, list):
                        assistant_blocks.extend(_strip_blocks(content))
    except OSError:
        pass

    flush_assistant()
    return messages


def _strip_blocks(blocks: list) -> list:
    out = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        btype = block.get("type", "")
        if btype == "text":
            text = strip_user_query_wrapper(strip_memory_tags(block.get("text", ""))).strip()
            if text:
                out.append({"type": "text", "text": text})
        elif btype in ("tool_use", "tool_result"):
            out.append(block)
    return out


def compose_recall_query(latest_query: str, messages: list, recall_context_turns: int, recall_roles: list = None) -> str:
    latest = strip_user_query_wrapper(strip_memory_tags(latest_query)).strip()
    if recall_context_turns <= 1 or not messages:
        return latest

    allowed_roles = set(recall_roles or ["user", "assistant"])
    contextual = slice_last_turns_by_user_boundary(messages, recall_context_turns)
    context_lines = []
    for msg in contextual:
        role = msg.get("role")
        if role not in allowed_roles:
            continue
        content = msg.get("content", "")
        if not isinstance(content, str):
            content = str(content)
        content = strip_memory_tags(content).strip()
        if not content or (role == "user" and content == latest):
            continue
        context_lines.append(f"{role}: {content}")

    if not context_lines:
        return latest
    return "Prior context:\n" + "\n".join(context_lines) + "\n\n" + latest


def truncate_recall_query(query: str, latest_query: str, max_chars: int) -> str:
    if max_chars <= 0 or len(query) <= max_chars:
        return query
    latest = strip_user_query_wrapper(latest_query).strip()
    if "Prior context:" not in query:
        return latest[:max_chars]
    suffix = "\n\n" + latest
    if len(suffix) >= max_chars:
        return latest[:max_chars]
    marker = "Prior context:\n"
    idx = query.find(marker)
    suffix_idx = query.rfind(suffix)
    if idx == -1 or suffix_idx == -1:
        return latest[:max_chars]
    lines = [ln for ln in query[idx + len(marker) : suffix_idx].split("\n") if ln]
    kept = []
    for i in range(len(lines) - 1, -1, -1):
        kept.insert(0, lines[i])
        candidate = f"{marker}{chr(10).join(kept)}{suffix}"
        if len(candidate) > max_chars:
            kept.pop(0)
            break
    return f"{marker}{chr(10).join(kept)}{suffix}" if kept else latest[:max_chars]


def slice_last_turns_by_user_boundary(messages: list, turns: int) -> list:
    if not messages or turns <= 0:
        return []
    user_turns = 0
    start = -1
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "user":
            user_turns += 1
            if user_turns >= turns:
                start = i
                break
    return list(messages) if start == -1 else messages[start:]


def format_memories(results: list) -> str:
    if not results:
        return ""
    lines = []
    for r in results:
        text = r.get("text", "")
        mem_type = r.get("type") or r.get("fact_type", "")
        mentioned_at = r.get("mentioned_at", "")
        type_str = f" [{mem_type}]" if mem_type else ""
        date_str = f" ({mentioned_at})" if mentioned_at else ""
        lines.append(f"- {text}{type_str}{date_str}")
    return "\n\n".join(lines)


def format_current_time() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")


def prepare_retention_transcript(
    messages: list,
    retain_roles: list = None,
    retain_full_window: bool = False,
    include_tool_calls: bool = False,
) -> tuple:
    if not messages:
        return None, 0

    if retain_full_window:
        target = messages
    else:
        last_user = -1
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].get("role") == "user":
                last_user = i
                break
        if last_user == -1:
            return None, 0
        target = messages[last_user:]

    allowed = set(retain_roles or ["user", "assistant"])
    if include_tool_calls:
        structured = []
        for msg in target:
            role = msg.get("role")
            if role not in allowed:
                continue
            content = msg.get("content", "")
            if isinstance(content, str):
                blocks = [{"type": "text", "text": strip_memory_tags(content).strip()}]
            else:
                blocks = _strip_blocks(content) if isinstance(content, list) else []
            if blocks:
                structured.append({"role": role, "content": blocks})
        if not structured:
            return None, 0
        transcript = json.dumps(structured, ensure_ascii=False)
        return (transcript, len(structured)) if len(transcript.strip()) >= 10 else (None, 0)

    parts = []
    for msg in target:
        role = msg.get("role")
        if role not in allowed:
            continue
        content = msg.get("content", "")
        if not isinstance(content, str):
            content = str(content)
        content = strip_memory_tags(content).strip()
        if content:
            parts.append(f"[role: {role}]\n{content}\n[{role}:end]")
    if not parts:
        return None, 0
    transcript = "\n\n".join(parts)
    return (transcript, len(parts)) if len(transcript.strip()) >= 10 else (None, 0)
