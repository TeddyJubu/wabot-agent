---
name: composio-gmail-calendar
description: Gmail and Google Calendar via Composio — always fetch live data; never invent emails or events.
---

# Gmail & Google Calendar (Composio)

**Read this skill** (`read_local_skill` → `composio-gmail-calendar`) before answering anything about email, inbox, threads, calendar, meetings, availability, or scheduling.

Gmail and Google Calendar are connected through Composio for this operator. Treat them as **live systems**, not things you can answer from chat memory or general knowledge.

## Mandatory workflow

1. **Search** — `COMPOSIO_SEARCH_TOOLS` with a clear intent (e.g. "list unread Gmail", "events today Google Calendar").
2. **Execute** — `COMPOSIO_MULTI_EXECUTE_TOOL` with the returned tool slugs and real parameters (limits, date ranges, query strings).
3. **Answer from tool output only** — subjects, senders, times, attendees, and counts must match the JSON returned. Quote or paraphrase faithfully; do not embellish.
4. **Re-fetch every turn** — even if the user asked the same thing a minute ago. Do not reuse stale summaries from earlier messages in the thread.
5. **Auth** — if execution fails with connection/auth errors, call `COMPOSIO_MANAGE_CONNECTIONS` and send the OAuth link; do not pretend you fetched mail or events.

## Never hallucinate

Do **not**:

- Invent email subjects, senders, snippets, or unread counts.
- Invent meetings, attendees, rooms, or free/busy blocks.
- Say "you have no emails" or "your calendar is clear" without a successful Composio fetch in **this** turn.
- Fill gaps when tools return empty, error, or timeout — report the actual outcome ("Composio returned no messages for that query" / "tool failed: …").

Do **not** store full email bodies or calendar dumps in `remember_contact_fact` / Mem0 — only stable preferences (e.g. timezone, "summarize inbox briefly").

## WhatsApp-friendly replies

After tools return:

- Summarize clearly (who / what / when).
- For lists, cap at what the user asked for (e.g. "last 5" → fetch with limit 5).
- Offer a next step ("Want me to draft a reply?" / "Should I create a calendar hold?") only after you have real data.

## Writes (send email, create event)

- Confirm recipient, subject, and time with the user when ambiguous.
- Use Composio execute tools for the write; never claim something was sent or scheduled without a successful tool result.
