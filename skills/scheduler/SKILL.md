---
name: scheduler
description: Schedule WhatsApp reminders and manage pending reminder jobs.
---

# Scheduler

Use this skill when the user asks to be reminded later, at a specific time, or on a schedule.

## Rules

- Always call `create_reminder` with a clear `message` and `due_at` in **ISO-8601 UTC**
  (example: `2026-05-19T14:30:00+00:00`). Convert the user's local time to UTC before calling.
- Default `target_jid` to the requester when they want the reminder on this chat; set `target_jid`
  explicitly when reminding a different contact.
- Confirm the scheduled time and target in your reply after `create_reminder` succeeds.
- Use `list_reminders` to show pending or past reminders; `cancel_reminder(id)` to cancel.
- Reminders fire as direct WhatsApp text (no LLM) when `WABOT_AGENT_REMINDERS_ENABLED=true`.

## Failure handling

- `invalid_due_at`: re-parse the time and pass ISO UTC.
- `pending_limit`: ask the user to cancel old reminders first.
- `reminders_disabled`: tell the operator to enable reminders on the VPS.
