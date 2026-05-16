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
- For inbound media, check `has_media` / `media_kind` on inbox rows, then call
  `download_whatsapp_media(chat, message_id)` to save under `data/media/inbound/`.
- Send files with `send_whatsapp_document`, `send_whatsapp_audio`, or `send_whatsapp_video`
  (paths must live under `WABOT_AGENT_MEDIA_DIR`). Images still use `send_whatsapp_image`.
- React with `react_whatsapp_message`; edit own messages with `edit_whatsapp_message`;
  revoke with `revoke_whatsapp_message` (pass `sender` for others' messages in groups).
- Create groups with `create_whatsapp_group`; inspect via `get_whatsapp_group`;
  invite links via `get_whatsapp_group_invite`; join via `join_whatsapp_group`.
- Mute, archive, or pin chats with `mute_whatsapp_chat`, `archive_whatsapp_chat`,
  `pin_whatsapp_chat` (syncs via WhatsApp app state).
- Profile metadata: `get_whatsapp_user_info(jid)` (status, picture id, verified business name).
  Avatars: `download_whatsapp_profile_picture` → `data/media/avatars/` (set `preview=true` for thumb).
- Read/delivery receipts and remote typing may appear on the dashboard SSE stream
  (`whatsapp_receipt`, `whatsapp_presence`) when wabot webhooks are configured.
- History sync backfill populates `inbound_messages` via `POST /whatsapp/history` (no auto-reply).
  Use inbox tools after linking; live traffic still arrives on `/whatsapp/inbound`.
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

