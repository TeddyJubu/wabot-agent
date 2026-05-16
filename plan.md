# wabot-agent roadmap

Compact handoff for continuing work without full chat history.

## Session snapshot (2026-05-16)

| Item | Value |
|------|--------|
| Dashboard | http://127.0.0.1:8787 |
| wabot daemon | http://127.0.0.1:7777 (loopback only) |
| wabot repo | `~/Desktop/Code-hub/wabot` |
| agent repo | `~/Desktop/Code-hub/wabot-agent/wabot-agent` |
| Model | `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` via OpenRouter |
| WhatsApp | Linked (`/ready` → wabot ready) |
| Send policy | `allow_all` in `data/runtime_overrides.json` (review for production) |
| wabot home | `WABOT_AGENT_WABOT_HOME` → wabot repo (powers **New QR** button) |

**Architecture:** Operator → wabot-agent (FastAPI + Agents SDK) → wabot HTTP API → whatsmeow → WhatsApp.

**“Omni” clarification:** Nemotron “Omni” = multimodal LLM name, not full WhatsApp access. Capabilities come from wabot/whatsmeow tools only.

---

## Completed in this session

### Operator UX
- [x] Local run: `uv sync`, `.env`, `uv run python main.py`
- [x] OpenRouter live model (Nemotron free)
- [x] Nemotron fix: omit `tool_choice` for `:free` / nemotron models (tools otherwise 404)
- [x] QR contrast: white panel + `SvgFillImage` white background in SVG
- [x] **New QR** button → `POST /api/whatsapp/pairing/restart` (restarts wabot via `WABOT_AGENT_WABOT_HOME`)
- [x] **Refresh** re-fetches current code only

### wabot daemon (`~/Desktop/Code-hub/wabot`)
- [x] `GET /inbox/recent` — ring buffer of observed inbound messages
- [x] `POST /contacts/lookup` — `IsOnWhatsApp`
- [x] `GET /groups` — `GetJoinedGroups`
- [x] `POST /chats/read` — `MarkRead`
- [x] `POST /presence/typing` — `SendChatPresence`

### wabot-agent tools
- [x] `list_whatsapp_inbound_messages`, `get_last_whatsapp_inbound_message`
- [x] `lookup_whatsapp_contacts`, `list_whatsapp_groups`, `mark_whatsapp_read`, `send_whatsapp_typing`
- [x] Existing: `wabot_health`, `send_whatsapp_text`, `send_whatsapp_image`, memory, skills

### Inbound pipeline
- [x] Webhook: wabot → `POST /whatsapp/inbound` (needs `WABOT_INBOUND_URL` + matching tokens)
- [x] Agent DB table `inbound_messages` (backup if daemon buffer empty)

---

## whatsmeow feature matrix

Legend: **Done** = exposed via wabot + agent tool. **Partial** = limited. **Missing** = not wired.

| whatsmeow category | Status | wabot API (target) | Agent tool |
|--------------------|--------|-------------------|------------|
| Session / connect / QR | **Done** | `/health`, `/pairing/qr` | pairing UI, New QR |
| Send text | **Done** | `POST /send` | `send_whatsapp_text` |
| Send image | **Done** | `POST /send-image` | `send_whatsapp_image` |
| Send video/audio/doc/sticker | **Partial** (doc/audio/video) | `POST /send-media` | `send_whatsapp_document/audio/video` |
| Receive messages (observe) | **Partial** | `GET /inbox/recent` + webhook | inbox tools |
| Download media | **Done** | `GET /media/download` | `download_whatsapp_media` |
| Contact lookup | **Done** | `POST /contacts/lookup` | `lookup_whatsapp_contacts` |
| User info / avatar | Missing | `GET /users/{jid}` | `get_whatsapp_user_info` |
| List groups | **Done** | `GET /groups` | `list_whatsapp_groups` |
| Group admin / invites | Missing | `/groups/*` | group tools |
| Mark read | **Done** | `POST /chats/read` | `mark_whatsapp_read` |
| Typing presence | **Done** | `POST /presence/typing` | `send_whatsapp_typing` |
| Receipt events | Missing | webhook `WABOT_RECEIPT_URL` | — |
| Presence events | Missing | webhook | — |
| Reactions / edit / revoke | Missing | `/messages/*` | — |
| Polls | Missing | `/polls/*` | — |
| App state (mute/pin/archive) | Missing | `/chats/{jid}/*` | — |
| History sync | Missing | background job | — |
| Blocklist / privacy | Missing | `/blocklist`, `/privacy` | — |
| Newsletters | Missing | `/newsletters/*` | — |
| Voice/video calls | N/A | whatsmeow does not support | — |
| Broadcast lists | N/A | not on WhatsApp Web | — |

**Unread badges:** Not a single whatsmeow API. Approximate with inbox + read receipts when message IDs are known from webhook/inbox.

---

## Implementation phases (remaining)

### Phase 2 — Media (done)
**wabot**
- [x] `GET /media/download?chat=&id=` — recent inbound media cache + `DownloadAny`
- [x] `POST /send-media` — document, audio, video (`kind` + multipart `file`)
- [x] Inbound webhook + inbox include `media_kind`, `media_mime`, `media_filename`, `has_media`

**wabot-agent**
- [x] `download_whatsapp_media` → `data/media/inbound/{chat}/…`
- [x] `send_whatsapp_document`, `send_whatsapp_audio`, `send_whatsapp_video`
- [x] `./scripts/verify-phase1.sh` (CI + live smoke; rename optional)

### Phase 3 — Message lifecycle + groups
**wabot**
- `POST /messages/react`, `PATCH /messages/edit`, `DELETE /messages/{id}` (revoke)
- `POST /groups`, `POST /groups/{jid}/invite`, `POST /groups/join`, `GET /groups/{jid}`

**wabot-agent**
- Matching agent tools; update `skills/whatsapp-operator/SKILL.md`

### Phase 4 — Events + app state
**wabot**
- Webhooks: `WABOT_RECEIPT_URL`, `WABOT_PRESENCE_URL` (optional)
- Subscribe to `events.Receipt`, `events.ChatPresence`, `events.HistorySync` (selective)
- `POST /chats/{jid}/mute`, archive, pin via app state APIs

**wabot-agent**
- SSE `pairing_changed`-style events for receipts/presence
- Tools for mute/archive when needed

---

## Conventions for new features

1. Add **wabot HTTP route** first (auth: `X-Token`, ready-gate like `/send`).
2. Add **WabotClient** method in `src/wabot_agent/wabot.py`.
3. Add **`@function_tool`** in `src/wabot_agent/tools.py` + register in `core_tools()`.
4. Update **`INSTRUCTIONS`** in `agent.py` and **`skills/whatsapp-operator/SKILL.md`**.
5. Tests: `tests/` in wabot-agent; `go test ./cmd/wabot/...` in wabot.
6. Rebuild UI if needed: `./scripts/build-web.sh`.
7. Restart **wabot** then **wabot-agent** (agent does not hot-reload `.env`).

---

## Local ops cheatsheet

```bash
# Agent
cd wabot-agent && uv run python main.py

# wabot
cd ~/Desktop/Code-hub/wabot && set -a && source ./wabot.env && set +a && ./wabot

# Rebuild web
./scripts/build-web.sh

# New QR (API)
curl -X POST http://127.0.0.1:8787/api/whatsapp/pairing/restart

# Inbox (daemon)
curl -H "X-Token: $(cat ~/.config/wabot/token)" http://127.0.0.1:7777/inbox/recent
```

---

## Security reminders

- Keep `.env`, `store.db`, tokens out of git.
- Production: `WABOT_AGENT_SEND_POLICY=allowlist`, not `allow_all`.
- wabot stays on `127.0.0.1`; use Cloudflare Tunnel + Access for remote pairing (see README).
- `data/runtime_overrides.json` may override model/policy — do not commit secrets.

---

## Open questions

1. Prioritize Phase 2 (media) vs Phase 4 (receipt webhooks for true “unread” UX)?
2. Should wabot history sync backfill inbox DB, or only live webhook + buffer?
3. Publish wabot inbox/groups APIs in upstream wabot README?
