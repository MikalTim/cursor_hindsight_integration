"""Hindsight MCP client over Streamable HTTP (no Python HindsightClient).

Talks to the same MCP server Cursor uses (e.g. user-hindsight-local at
http://localhost:8888/mcp/). Uses stdlib only.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional


def _plugin_version() -> str:
    from pathlib import Path

    manifest = Path(__file__).resolve().parents[2] / "settings.json"
    try:
        return json.loads(manifest.read_text()).get("version", "0.0.0")
    except (OSError, ValueError):
        return "0.0.0"


USER_AGENT = f"hindsight-cursor/{_plugin_version()}"


def _validate_mcp_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"MCP URL must use http or https, got: {parsed.scheme!r}")
    if not parsed.hostname:
        raise ValueError(f"MCP URL has no hostname: {url!r}")
    base = url.rstrip("/")
    return base if base.endswith("/mcp") else f"{base}/mcp"


class HindsightMcpClient:
    """Minimal MCP Streamable HTTP client for Hindsight tools."""

    def __init__(self, mcp_url: str, timeout: int = 15):
        self.mcp_url = _validate_mcp_url(mcp_url)
        self.timeout = timeout
        self._session_id: Optional[str] = None
        self._request_id = 0

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _parse_sse(self, raw: str) -> list[dict]:
        messages = []
        for block in re.split(r"\n\n+", raw.strip()):
            data_lines = [
                line[5:].strip()
                for line in block.split("\n")
                if line.startswith("data:")
            ]
            if not data_lines:
                continue
            try:
                messages.append(json.loads("\n".join(data_lines)))
            except json.JSONDecodeError:
                continue
        return messages

    def _post(self, payload: dict, session_id: Optional[str] = None) -> list[dict]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": USER_AGENT,
        }
        if session_id:
            headers["mcp-session-id"] = session_id

        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{self.mcp_url}/",
            data=data,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode()
                if not session_id and resp.headers.get("mcp-session-id"):
                    self._session_id = resp.headers.get("mcp-session-id")
                return self._parse_sse(body)
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode()
            except Exception:
                pass
            raise RuntimeError(f"HTTP {e.code} from MCP {self.mcp_url}: {detail}") from e

    def _ensure_session(self) -> str:
        if self._session_id:
            return self._session_id

        init_messages = self._post(
            {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "hindsight-cursor-hook", "version": _plugin_version()},
                },
            }
        )
        for msg in init_messages:
            if msg.get("error"):
                raise RuntimeError(f"MCP initialize failed: {msg['error']}")

        if not self._session_id:
            raise RuntimeError("MCP initialize did not return mcp-session-id header")

        self._post(
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            session_id=self._session_id,
        )
        return self._session_id

    def _call_tool(self, name: str, arguments: dict) -> Any:
        session = self._ensure_session()
        messages = self._post(
            {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            },
            session_id=session,
        )

        for msg in messages:
            if msg.get("error"):
                raise RuntimeError(f"MCP tool {name} failed: {msg['error']}")
            result = msg.get("result")
            if result is None:
                continue
            if result.get("isError"):
                raise RuntimeError(f"MCP tool {name} returned error: {result}")

            structured = result.get("structuredContent")
            if isinstance(structured, dict):
                if "result" in structured:
                    inner = structured["result"]
                    if isinstance(inner, str):
                        try:
                            return json.loads(inner)
                        except json.JSONDecodeError:
                            return inner
                    return inner
                return structured

            for block in result.get("content") or []:
                if block.get("type") == "text":
                    text = block.get("text", "")
                    try:
                        return json.loads(text)
                    except json.JSONDecodeError:
                        return text

        return None

    def health_check(self) -> bool:
        try:
            self._ensure_session()
            return True
        except Exception:
            return False

    def recall(
        self,
        query: str,
        bank_id: Optional[str] = None,
        max_tokens: int = 1024,
        budget: str = "mid",
        types: Optional[list] = None,
    ) -> dict:
        args: dict[str, Any] = {
            "query": query,
            "max_tokens": max_tokens,
            "budget": budget,
        }
        if bank_id:
            args["bank_id"] = bank_id
        if types:
            args["types"] = types
        result = self._call_tool("recall", args)
        if isinstance(result, dict) and "results" in result:
            return result
        if isinstance(result, dict):
            return result
        return {"results": []}

    def retain(
        self,
        content: str,
        bank_id: Optional[str] = None,
        document_id: Optional[str] = None,
        context: Optional[str] = None,
        metadata: Optional[dict] = None,
        tags: Optional[list] = None,
    ) -> dict:
        args: dict[str, Any] = {"content": content}
        if bank_id:
            args["bank_id"] = bank_id
        if document_id:
            args["document_id"] = document_id
        if context:
            args["context"] = context
        if metadata:
            args["metadata"] = {k: str(v) for k, v in metadata.items()}
        if tags:
            args["tags"] = tags
        result = self._call_tool("retain", args)
        return result if isinstance(result, dict) else {}

    def update_bank_mission(
        self,
        bank_id: str,
        mission: str,
        retain_mission: Optional[str] = None,
    ) -> dict:
        updates: dict[str, str] = {"reflect_mission": mission}
        if retain_mission:
            updates["retain_mission"] = retain_mission
        result = self._call_tool(
            "update_bank",
            {
                "bank_id": bank_id,
                "config_updates": updates,
            },
        )
        return result if isinstance(result, dict) else {}
