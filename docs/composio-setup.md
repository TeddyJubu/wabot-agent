# Composio (Gmail, GitHub, Slack, …)

wabot-agent uses **Composio native tools** with the Python OpenAI Agents SDK (same flow as the [Composio quickstart](https://docs.composio.dev/docs/quickstart), not the TypeScript packages).

Your `COMPOSIO_API_KEY` (`ak_…` from [platform.composio.dev/settings](https://platform.composio.dev/settings)) powers the **tool router API**. It is **not** the same as the optional `x-consumer-api-key` used only for `https://connect.composio.dev/mcp` (MCP often returns 401 with project keys that work fine for native tools).

## Enable on the VPS

```bash
COMPOSIO_API_KEY=ak_your_key_here
WABOT_AGENT_COMPOSIO_ENABLED=true
```

Restart `wabot-agent`. On each run, the agent:

1. Creates or reuses a Composio session for the WhatsApp `user_id` / group JID (stored in SQLite as `composio_session_id`).
2. Attaches six meta-tools (`COMPOSIO_SEARCH_TOOLS`, `COMPOSIO_MANAGE_CONNECTIONS`, …) to the agent for that turn.

When native Composio is enabled, the **Composio MCP server** in `configs/mcp.composio.json` is skipped automatically (avoids duplicate tools and MCP 401s).

## OAuth in chat

When a toolkit needs auth, the agent calls `COMPOSIO_MANAGE_CONNECTIONS` and should paste the **OAuth URL** in the WhatsApp reply. Open it on your phone, approve once, then ask again.

You can also pre-connect apps under [dashboard.composio.dev → Connect Apps](https://dashboard.composio.dev/).

## MCP alternative (optional)

See [composio-mcp-setup.md](composio-mcp-setup.md) if you specifically want remote MCP instead of native tools. Do not enable both for the same Composio account unless you know you need both.
