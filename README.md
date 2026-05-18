# wabot-agent

[![CI](https://github.com/TeddyJubu/wabot-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/TeddyJubu/wabot-agent/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Open-source WhatsApp automation agent ([MIT](LICENSE)). Fork, self-host, and contribute — see [CONTRIBUTING.md](CONTRIBUTING.md) and [DISTRIBUTION.md](DISTRIBUTION.md).

Production-oriented WhatsApp automation: **OpenAI Agents SDK** + **OpenRouter**, with [`wabot`](https://github.com/TeddyJubu/wabot) (whatsmeow) as the only send/receive path.

![Architecture](docs/agent-interactions.png)

## Features

- FastAPI control plane with operator dashboard (React SPA at `/`)
- Mobile-friendly WhatsApp pairing at `/pair` (live QR via SSE)
- Simple sign-in at `/login` (dashboard password + session cookie)
- Guarded agent tools (send policy, allowlist, dry-run default)
- SQLite memory: inbound messages, contact facts, runs, idempotency
- Webhooks from wabot: inbound, receipt, presence, history backfill
- VPS deploy scripts, production hygiene checks, optional Cloudflare Tunnel

## Distribution

To ship this project to someone else (tarball, no secrets):

```bash
chmod +x scripts/package-release.sh scripts/install-from-release.sh
./scripts/package-release.sh
# → dist/wabot-agent-0.1.0.tar.gz + .sha256
```

Recipients follow **[DISTRIBUTION.md](DISTRIBUTION.md)** (wabot install, `.env`, VPS bootstrap). Package a specific branch with `REF=my-version ./scripts/package-release.sh`.

## Quickstart (local)

```bash
uv sync --all-extras
cp .env.example .env
./scripts/build-web.sh
uv run python main.py
```

Open [http://127.0.0.1:8787/login](http://127.0.0.1:8787/login) (or [http://127.0.0.1:8787](http://127.0.0.1:8787) with `?token=` if `WABOT_AGENT_OPERATOR_TOKEN` is set).

Without `OPENROUTER_API_KEY`, the agent runs in **offline mode** (boot and test without network credentials).

### Frontend dev (HMR)

```bash
cd web && npm install && npm run dev    # http://127.0.0.1:5173
uv run python main.py                   # http://127.0.0.1:8787
```

Vite proxies `/api`, `/whatsapp`, `/health`, and `/ready` to FastAPI.

## Prerequisites: wabot

Clone and pair [wabot](https://github.com/TeddyJubu/wabot) on the same host (loopback only):

```bash
git clone https://github.com/TeddyJubu/wabot.git
cd wabot && ./scripts/install.sh
wa setup && wa doctor && wa health
```

Agent `.env` (see `.env.example`):

```dotenv
WABOT_ENDPOINT=http://127.0.0.1:7777
WABOT_TOKEN=...
WABOT_INBOUND_TOKEN=...
```

Point wabot webhooks at the agent (loopback in production):

```dotenv
WABOT_INBOUND_URL=http://127.0.0.1:8787/whatsapp/inbound
WABOT_RECEIPT_URL=http://127.0.0.1:8787/whatsapp/receipt
WABOT_PRESENCE_URL=http://127.0.0.1:8787/whatsapp/presence
WABOT_HISTORY_SYNC_URL=http://127.0.0.1:8787/whatsapp/history-sync
WABOT_HISTORY_URL=http://127.0.0.1:8787/whatsapp/history
```

Never expose the wabot daemon (`:7777`) on the public internet.

## Operator authentication

| Layer | Purpose |
|--------|---------|
| **`/login`** | Browser sign-in with `WABOT_AGENT_DASHBOARD_PASSWORD` (or operator token); sets a 30-day HttpOnly cookie |
| **`WABOT_AGENT_OPERATOR_TOKEN`** | API header `X-Operator-Token` / `Authorization: Bearer` for scripts |
| **Cloudflare Access** (optional) | Edge identity when `WABOT_AGENT_CF_ACCESS_REQUIRED=true` |

Legacy bootstrap still works: `https://your-host/?token=<operator-token>` once, then the cookie is minted.

## Send policy

```dotenv
WABOT_AGENT_SEND_POLICY=allowlist
WABOT_AGENT_ALLOWED_RECIPIENTS=1234567890@lid,other@lid
```

Defaults to `dry_run` in `.env.example`. Use `allow_all` only in controlled environments.

Apply production defaults (allowlist, loopback checks, history URLs in `wabot.env`, operator token generation):

```bash
uv run python scripts/apply-production-hygiene.py
./scripts/check-production-hygiene.sh
```

Restart `wabot-agent` after hygiene changes.

## VPS file processing (attachments)

On a production VPS, install **system tools** once, then configure **Whisper** and **vision** in `.env`. Inbound files are downloaded and processed automatically; owners get higher-quality speech recognition.

### 1. System packages (once per VPS)

```bash
sudo APP_DIR=/opt/wabot-agent APP_USER=wabotagent \
  bash /opt/wabot-agent/scripts/install-vps-processing-tools.sh
```

Installs: `ffmpeg`, `ffprobe`, `pdftotext`, `pdfinfo`, `tesseract-ocr`, `file`, `unzip`.  
Skipped on purpose (too heavy): LibreOffice, Pandoc.

`scripts/bootstrap-vps.sh` runs this step automatically when the script is present.

### 2. Python dependencies

Deployed via `uv sync` (includes `faster-whisper`, `pypdf`). After deploy, restart:

```bash
sudo systemctl restart wabot-agent
```

### 3. Environment variables

```dotenv
# Auto-download + extract inbound attachments on the VPS
WABOT_AGENT_FILE_PROCESS_INBOUND=true
WABOT_AGENT_FILE_USE_SYSTEM_TOOLS=true
WABOT_AGENT_FILE_OCR_ENABLED=true
WABOT_AGENT_FILE_EXCERPT_LIMIT=12000
WABOT_AGENT_FILE_MAX_PROCESS_BYTES=20971520

# Vision (photos) — requires a vision-capable LLM (e.g. gemma4 via Ollama Cloud)
WABOT_AGENT_VISION_ATTACH_IMAGES=true

# Speech-to-text: tiny for everyone; base for owner_numbers + dashboard chat
WABOT_AGENT_WHISPER_MODEL=tiny
WABOT_AGENT_WHISPER_MODEL_OWNER=small
WABOT_AGENT_WHISPER_MAX_SECONDS=90
WABOT_AGENT_WHISPER_BEAM_SIZE_OWNER=5
# WABOT_AGENT_WHISPER_LANGUAGE=en

# Owner numbers (for send policy + better Whisper on their voice notes)
WABOT_AGENT_OWNER_NUMBERS=+6580286424,+8801521207499
```

| Variable | Purpose |
|----------|---------|
| `WABOT_AGENT_FILE_PROCESS_INBOUND` | Download and process attachments on each inbound message |
| `WABOT_AGENT_VISION_ATTACH_IMAGES` | Pass image pixels to the LLM (not just OCR) |
| `WABOT_AGENT_WHISPER_MODEL` | Default Whisper model (`tiny` — low CPU/RAM) |
| `WABOT_AGENT_WHISPER_MODEL_OWNER` | Whisper for owners/dashboard (`small` on 8GB RAM; use `medium` if you have headroom) |
| `WABOT_AGENT_WHISPER_LANGUAGE` | Force language code (`en`, `bn`, …) when auto-detect is wrong |
| `WABOT_AGENT_WHISPER_BEAM_SIZE_OWNER` | Decoder beam width for owners (default `5`; was `1` before — very inaccurate) |
| `WABOT_AGENT_WHISPER_MAX_SECONDS` | Max audio transcribed per file (truncates long voice notes) |

### 4. What gets processed automatically

| Type | VPS handling |
|------|----------------|
| Images | Vision LLM + optional Tesseract OCR |
| PDF | `pdftotext` → `pypdf` → **page OCR** (`pdftoppm` + Tesseract for screencapture/scanned) |
| Audio / voice notes | ffmpeg → Whisper (`tiny` or `base` by sender) |
| Video | ffprobe + frame OCR + audio transcript |
| DOCX | Text extraction (no LibreOffice) |
| Text, CSV, JSON, ZIP | Read or list contents |

### 5. Agent tools (manual / follow-up)

| Tool | Use |
|------|-----|
| `process_whatsapp_attachment(chat, message_id)` | Re-download and process a cached attachment |
| `process_vps_file(path)` | Process any file under `data/media/` or `data/` |
| `send_whatsapp_file(to, path)` | Send any file type from the media directory |
| `search_web` / `search_images` | Find pages or image URLs on the web (no API key) |
| `fetch_url_to_media(url)` | Download a public URL into `data/media/downloads/` |
| `download_whatsapp_media` | Save attachment to disk only |

See `skills/whatsapp-operator/SKILL.md` for operator guidance.

### 6. RAM notes (typical 8GB VPS)

- `tiny` Whisper ≈ low hundreds of MB; `base` ≈ ~1GB when loaded.
- Both models may be cached after first use; only one runs at a time (locked).
- Use `small` instead of `base` if RAM is tight.

## Production VPS

1. Bootstrap once: `sudo APP_DIR=/opt/wabot-agent APP_USER=wabotagent ./scripts/bootstrap-vps.sh`
2. Configure `/opt/wabot-agent/.env` and `/opt/wabot/wabot.env` (tokens, OpenRouter, allowlist).
3. Deploy from your machine: `SSH_HOST=your-host APP_DIR=/opt/wabot-agent ./scripts/deploy-to-vignesh.sh`
4. Put HTTPS in front of the agent only (e.g. Caddy → `127.0.0.1:8787`). Use `/login` + `/pair` for onboarding.
5. Set `WABOT_AGENT_WABOT_HOME=/opt/wabot` so **New QR** works in the pairing UI.

Pairing checklist for a new operator:

1. Reset any old linked device (WhatsApp → Linked devices, or dashboard **New QR**).
2. Share `https://<your-domain>/login` and the dashboard password (secure channel).
3. Open `https://<your-domain>/pair` and scan the QR.
4. Add their JID to `WABOT_AGENT_ALLOWED_RECIPIENTS` after the first inbound message.

Optional: [Cloudflare Tunnel + Access](docs/superpowers/specs/2026-05-15-public-pairing-website-design.md) via `scripts/setup-cloudflared.sh`.

## HTTP API (summary)

```text
GET   /health
GET   /login
POST  /api/auth/login
GET   /ready                          # requires operator auth
GET   /api/whatsapp/pairing
POST  /api/whatsapp/pairing/restart
POST  /api/chat
POST  /api/chat/stream
GET   /api/stream                     # SSE
GET   /api/settings
PATCH /api/settings
POST  /whatsapp/inbound               # wabot webhook (Bearer)
POST  /whatsapp/history               # history backfill batches
POST  /whatsapp/history-sync
POST  /whatsapp/receipt
POST  /whatsapp/presence
```

Inbound webhook shape:

```json
{
  "id": "message-id",
  "timestamp": "2026-05-13T12:00:00Z",
  "from": "1234567890@lid",
  "chat": "1234567890@lid",
  "is_group": false,
  "text": "hello"
}
```

## Context management

Long chats stay fast by default:

- **Session window** — only the latest `WABOT_AGENT_SESSION_HISTORY_LIMIT` turns are loaded (default 48).
- **Token budget** — older history is dropped or shrunk to fit `WABOT_AGENT_SESSION_MAX_HISTORY_TOKENS` (default 20k); images in history become placeholders.
- **Per-turn cap** — inbound file excerpts and attachments are truncated to `WABOT_AGENT_PROMPT_MAX_CHARS`.
- **SQLite retention** — `agent_messages` rows per contact are pruned to `WABOT_AGENT_SESSION_DB_KEEP_ITEMS`; audit tables (`inbound_messages`, `runs`, `tool_events`) are capped on a schedule.
- **LLM summaries** — when history is trimmed or pruned, dropped turns are summarized into `session_summaries` and injected as `[Earlier conversation summary]` on the next run (`thread_summary.py`).

Tune in `.env` or see `src/wabot_agent/context_management.py`.

## Agent tools

Core WhatsApp tools include inbox reads, send text/image/media/**any file** (`send_whatsapp_file`), VPS file processing (`process_vps_file`, `process_whatsapp_attachment`), contacts, groups, read/typing, reactions, mute/archive/pin, and profile info. See `src/wabot_agent/tools.py` and `skills/whatsapp-operator/SKILL.md`. For attachment setup on a new VPS, see **VPS file processing** above.

## Verification

```bash
uv run ruff check .
uv run pytest -q -m "not live"
uv run python evals/run_local.py
cd web && npm run test -- --run && npm run build
```

With wabot running: `./scripts/verify-phase1.sh` (or `SKIP_LIVE=1`).

## Repository layout

```text
src/wabot_agent/     # FastAPI app, agent, tools, memory
web/                 # React dashboard (Vite)
static/              # Built SPA (scripts/build-web.sh)
scripts/             # deploy, hygiene, build-web, cloudflared
deploy/              # systemd, cloudflared examples
skills/              # Local agent skills
tests/               # Offline pytest suite
plan.md              # Roadmap and handoff
docs/                # Architecture diagrams and design specs
```

## License

Released under the [MIT License](LICENSE). Copyright (c) 2026 TeddyJubu and contributors.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Roadmap: [plan.md](plan.md).

## Safety

- Keep `.env`, `data/`, `store.db`, and tokens out of git.
- wabot binds to loopback; only the agent dashboard is public HTTPS.
- Use allowlists in production; rotate secrets if they appear in logs or chat.
- Inbound messages are stored even when auto-reply fails (OpenRouter errors do not drop the webhook).
