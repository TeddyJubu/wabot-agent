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

## Gmail & Google Calendar (no hallucinations)

When Gmail and Calendar are connected, the agent:

- Injects a **per-turn** reminder to call `COMPOSIO_SEARCH_TOOLS` + `COMPOSIO_MULTI_EXECUTE_TOOL` before stating any mail or calendar facts.
- Loads the **`composio-gmail-calendar`** skill (`skills/composio-gmail-calendar/SKILL.md`) — use `read_local_skill` for detailed rules.
- **Re-fetches on every turn** — it must not reuse stale inbox/event summaries from chat history.
- **Fails closed** — if tools error or return empty, it reports that; it does not invent subjects, times, or attendees.

Verify from WhatsApp or dashboard chat: *"What are my last 3 unread emails?"* — you should see Composio tool calls in the run log before the reply.

## MCP alternative (optional)

See [composio-mcp-setup.md](composio-mcp-setup.md) if you specifically want remote MCP instead of native tools. Do not enable both for the same Composio account unless you know you need both.
