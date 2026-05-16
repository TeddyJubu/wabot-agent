---
name: whatsapp-operator
description: Operating guidance for safe WhatsApp automation through wabot.
---

# WhatsApp Operator

Use this skill before changing WhatsApp state, sending messages, or handling inbound automation.

## Rules

- Check `wabot_health` before assuming WhatsApp is linked and connected.
- For "who messaged me" / recent chat questions, call `get_last_whatsapp_inbound_message`
  or `list_whatsapp_inbound_messages`. These read inbound traffic wabot observed — not
  WhatsApp app unread badges.
- Use `lookup_whatsapp_contacts` before cold messaging unknown numbers.
- Use `list_whatsapp_groups` for group discovery; `mark_whatsapp_read` when you have
  message IDs; `send_whatsapp_typing` for composing indicators.
- Never send credentials, one-time codes, tokens, cookies, or session data.
- Keep outbound messages short, clear, and human-readable.
- Respect the configured send policy. If a recipient is blocked, explain the operator action needed.
- Avoid bulk or cold outreach. Escalate to the operator instead.
- Store only useful, non-secret memory. Prefer concise facts with a source.

## Failure Handling

- `401`: token mismatch or missing `WABOT_TOKEN`; do not retry sends.
- `429`: rate limited; wait for the operator or retry later.
- `503`: WhatsApp is not connected or linked; ask the operator to repair the device session.
- Network timeout: check the VPS service and `wabot` daemon health.

