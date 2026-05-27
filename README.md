# Hindsight for Cursor

Long-term memory for [Cursor](https://cursor.com) — same workflow as the [Codex integration](codex_hindsight_integration (sibling repo, if used)), but hooks call **Hindsight via MCP** (no `HindsightClient` / REST).

Uses the same MCP server as the IDE (`user-hindsight-local` → `http://localhost:8888/mcp/` by default).

## How it works

| Cursor hook | Codex equivalent | Action |
|-------------|------------------|--------|
| `sessionStart` | `SessionStart` | MCP health check |
| `beforeSubmitPrompt` | `UserPromptSubmit` | MCP `recall` → inject `additional_context` |
| `stop` | `Stop` | MCP `retain` from `transcript_path` |

## Requirements

- **Cursor** with [hooks](https://cursor.com/docs/hooks) enabled
- **Python 3.9+**
- **Hindsight MCP** running (this repo: `hindsight-local` in `~/.cursor/mcp.json`)

## Installation

1. Ensure Hindsight MCP is configured (already in this workspace):

```json
"hindsight-local": {
  "url": "http://localhost:8888/mcp/",
  "type": "http"
}
```

2. Hooks are wired in [`.cursor/hooks.json`](../hooks.json) (project-level).

3. Optional user overrides — stable across updates:

```bash
mkdir -p ~/.hindsight
```

`~/.hindsight/cursor.json`:

```json
{
  "mcpUrl": "http://localhost:8888/mcp",
  "bankId": "my-project-memory",
  "dynamicBankId": true,
  "dynamicBankGranularity": ["agent", "project"]
}
```

## Configuration

| Key | Default | Description |
|-----|---------|-------------|
| `mcpUrl` | `http://localhost:8888/mcp` | Hindsight MCP HTTP endpoint (same as Cursor MCP server) |
| `bankId` | `watchdog-docker-deployment` | Memory bank ID |
| `autoRecall` | `true` | Recall before each prompt |
| `autoRetain` | `true` | Retain after each agent turn |
| `retainEveryNTurns` | `10` | Retain every N stops (1 = every turn) |
| `recallBudget` | `mid` | `low` / `mid` / `high` |
| `recallMaxTokens` | `1024` | Max tokens injected |
| `dynamicBankId` | `false` | Per-project banks (`cursor::project-name`) |
| `debug` | `false` | Log to stderr |

Environment overrides: `HINDSIGHT_MCP_URL`, `HINDSIGHT_BANK_ID`, `HINDSIGHT_AUTO_RECALL`, `HINDSIGHT_DEBUG`, etc. (see `hooks/lib/config.py`).

## MCP vs Codex REST

The Codex plugin uses `HindsightClient` (HTTP `/v1/default/banks/...`). This port uses **MCP `tools/call`** (`recall`, `retain`, `update_bank`) over Streamable HTTP — the same API surface agents use in chat.

No local `hindsight-embed` daemon management in hooks; the MCP server must already be running.

## Transcripts

Hooks read `transcript_path` from hook stdin (or `CURSOR_TRANSCRIPT_PATH`). Format: JSONL with `role` + `message.content` blocks (Cursor agent transcripts).

## Troubleshooting

- **Hooks not running**: Cursor → Settings → Hooks; restart Cursor after editing `hooks.json`.
- **Recall not injected**: `beforeSubmitPrompt` `additional_context` support varies by Cursor version; enable `debug: true` and check stderr / Hooks output channel.
- **MCP errors**: Confirm `curl http://localhost:8888/health` and that `hindsight-local` matches `mcpUrl` in settings.
- **Empty retain**: Enable transcripts in Cursor; verify `transcript_path` is non-null in hook input.

## Related

- [`.cursor/rules/hindsight-memory.mdc`](../rules/hindsight-memory.mdc) — agent guidance for manual MCP use
- [`.cursor/skills/hindsight-docs/`](../skills/hindsight-docs/) — retain/recall best practices
