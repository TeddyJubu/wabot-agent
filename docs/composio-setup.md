# Composio (Gmail, Calendar, GitHub, Slack, ...)

wabot-agent uses **Composio native tools** with the Python OpenAI Agents SDK (same flow as the [Composio quickstart](https://docs.composio.dev/docs/quickstart), not the TypeScript packages).

Your `COMPOSIO_API_KEY` (`ak_…` from [platform.composio.dev/settings](https://platform.composio.dev/settings)) powers the **tool router API**. It is **not** the same as the optional `x-consumer-api-key` used only for `https://connect.composio.dev/mcp` (MCP often returns 401 with project keys that work fine for native tools).

## Enable on the VPS

```bash
COMPOSIO_API_KEY=ak_your_key_here
WABOT_AGENT_COMPOSIO_ENABLED=true
# Optional but recommended for owner-calendar booking:
WABOT_AGENT_COMPOSIO_USER_ID=operator
```

Restart `wabot-agent`. On each run, the agent:

1. Creates or reuses a Composio session (stored in SQLite as `composio_session_id`).
2. Attaches six meta-tools (`COMPOSIO_SEARCH_TOOLS`, `COMPOSIO_MANAGE_CONNECTIONS`, …) to the agent for that turn.

If `WABOT_AGENT_COMPOSIO_USER_ID` is set, every turn reuses that one owner/admin
Composio session. This is recommended when the bot books against the owner's
calendar: the owner connects Google Calendar once, and clients do not need to
connect their own Google accounts just to request a meeting.

When native Composio is enabled, the **Composio MCP server** in `configs/mcp.composio.json` is skipped automatically (avoids duplicate tools and MCP 401s).

## WhatsApp is not Composio

WhatsApp is handled only by the native `wabot` service and the local `send_whatsapp_*`,
`lookup_whatsapp_contacts`, group, media, and readiness tools. Do not connect WhatsApp
inside Composio, do not ask the operator to approve a Composio WhatsApp link, and do not
use Composio `WHATSAPP_*` tools if Composio advertises them.

For appointment booking, use Composio only for Google Calendar availability/event work.
Use native wabot tools for the attendee's WhatsApp lookup and outreach.

## OAuth in chat

When a non-WhatsApp toolkit needs auth, the agent calls `COMPOSIO_MANAGE_CONNECTIONS`
and should paste the **OAuth URL** in the WhatsApp reply. Open it on your phone,
approve once, then ask again.

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
