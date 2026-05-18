# Composio MCP (1000+ app integrations)

wabot-agent can use [Composio Connect](https://docs.composio.dev/docs/composio-connect) as a remote MCP server so the agent can search tools, connect OAuth apps on demand, and run actions (Gmail, Notion, Slack, GitHub, etc.) through Composio’s meta-tools.

## 1. API key (dashboard)

1. Open [Composio dashboard → MCP getting started](https://dashboard.composio.dev/syeedmdjobayer/MCP/getting-started) (or **AI Clients** in the sidebar).
2. Create or select a client (e.g. **Custom** / **OpenAI Agents**).
3. Copy the **API key** (used as `x-consumer-api-key`).

Do not commit the key. Set it only in `.env` on the VPS or dev machine.

## 2. Enable in wabot-agent

In `wabot-agent/.env`:

```bash
COMPOSIO_API_KEY=your_key_here
WABOT_AGENT_MCP_CONFIG=./configs/mcp.composio.json
```

Restart wabot-agent. On startup, the agent connects to `https://connect.composio.dev/mcp` (Streamable HTTP). If the key is missing or invalid, that server is dropped (`drop_failed_servers=True`) and the agent still runs with local tools only.

## 3. Connect apps

When the agent needs an app, Composio returns an OAuth link — open it in a browser and approve. You can also pre-connect apps under **Connect Apps** in the [dashboard](https://dashboard.composio.dev/).

## 4. Verify

From dashboard chat or WhatsApp (owner), ask something that needs an external app (e.g. “list my last Gmail” after connecting Gmail). The agent should call Composio search/connection tools before executing.

Check logs for MCP connection errors if tools never appear.

## Config reference

| File | Purpose |
|------|---------|
| `configs/mcp.composio.json` | Composio Connect only (`enabled: true`) |
| `configs/mcp.example.json` | Local stdio example (disabled) |

Headers support `${ENV_VAR}` expansion (see `COMPOSIO_API_KEY` in `mcp.composio.json`).

## Security

- `require_approval` is set to **`always`** for Composio MCP tool calls (approval-first, same as the example MCP config).
- Never put `COMPOSIO_API_KEY` in the MCP JSON file or in git.
- Composio actions run in your Composio account; review connected apps in the dashboard regularly.

## Cursor / other IDEs

To use the same Composio account in Cursor, add to `.cursor/mcp.json` (see [Composio + Cursor](https://composio.dev/toolkits/composio/framework/cursor)):

```json
{
  "mcpServers": {
    "composio": {
      "url": "https://connect.composio.dev/mcp",
      "headers": {
        "x-consumer-api-key": "YOUR_API_KEY"
      }
    }
  }
}
```

That is separate from wabot-agent’s `WABOT_AGENT_MCP_CONFIG` — configure both if you want Composio in the IDE and on the VPS agent.
