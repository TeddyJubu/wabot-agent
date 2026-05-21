# wabot-agent

[![CI](https://github.com/TeddyJubu/wabot-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/TeddyJubu/wabot-agent/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Open-source WhatsApp automation agent ([MIT](LICENSE)). Production-oriented stack: **OpenAI Agents SDK**, your choice of **LLM provider**, and [`wabot`](https://github.com/TeddyJubu/wabot) (whatsmeow) as the only send/receive path.

Fork, self-host, and contribute — see [CONTRIBUTING.md](CONTRIBUTING.md) and [DISTRIBUTION.md](DISTRIBUTION.md).

![Architecture](docs/agent-interactions.png)

## Features

- FastAPI control plane with operator dashboard (React SPA at `/`)
- Mobile-friendly WhatsApp pairing at `/pair` (live QR via SSE)
- Sign-in at `/login` (dashboard password or operator token)
- Guarded agent tools (send policy, allowlist, dry-run)
- SQLite memory: inbound messages, contact facts, runs, idempotency
- Optional **Mem0** semantic memory (per person, across DMs and groups)
- Optional **Composio** tool router (Gmail, GitHub, Slack, …)
- Optional **Firecrawl** deep web research sidecar
- Inbound attachment processing (PDF, images, voice, video)
- Webhooks from wabot: inbound, receipt, presence, history backfill
- VPS deploy scripts, hygiene checks, optional Cloudflare Tunnel

---

## Dependency guide

Everything the project can talk to, what you must install, and what each piece needs in `.env`.

### Overview

```text
┌─────────────────────────────────────────────────────────────────┐
│  Browser  →  HTTPS (Caddy / Cloudflare)  →  wabot-agent :8787   │
│                     React SPA (static/) + FastAPI               │
└────────────────────────────┬────────────────────────────────────┘
                             │ loopback only
         ┌───────────────────┼───────────────────┐
         ▼                   ▼                   ▼
   wabot :7777        LLM provider      Optional services
   (WhatsApp)         (pick one)        (Mem0, Composio, Firecrawl)
```

| Tier | Component | Required? | Install |
|------|-----------|-----------|---------|
| **Runtime** | Python 3.12+, [uv](https://docs.astral.sh/uv/) | Yes | `uv sync` |
| **Runtime** | Node.js 20+ (build dashboard) | Yes for deploy | `scripts/build-web.sh` |
| **Core** | [wabot](https://github.com/TeddyJubu/wabot) daemon | Yes | Separate repo; loopback `:7777` |
| **LLM** | OpenRouter, Ollama local, or Ollama Cloud | One of three | See [LLM providers](#llm-providers-pick-one) |
| **Memory** | Mem0 + local Qdrant + FastEmbed | Optional | Enabled in `.env`; see [docs/mem0-setup.md](docs/mem0-setup.md) |
| **Integrations** | Composio native tools | Optional | `COMPOSIO_API_KEY`; see [docs/composio-setup.md](docs/composio-setup.md) |
| **Integrations** | Firecrawl web-agent | Optional | Node sidecar `:3000`; see [docs/web-agent-setup.md](docs/web-agent-setup.md) |
| **Integrations** | Composio Connect MCP | Optional | Often needs a different key than `ak_`; see [docs/composio-mcp-setup.md](docs/composio-mcp-setup.md) |
| **Auth (UI)** | Clerk | Optional | `VITE_CLERK_PUBLISHABLE_KEY` in `web/.env` |
| **VPS media** | ffmpeg, poppler, tesseract | Recommended on VPS | `scripts/install-vps-processing-tools.sh` |

---

### Runtime (always)

| Tool | Version | Purpose |
|------|---------|---------|
| **Python** | ≥ 3.12 | Agent, API, tools |
| **uv** | latest | Lockfile install (`uv.lock`) |
| **Node.js** | 20+ | Build `web/` → `static/`; Firecrawl sidecar |

```bash
uv sync --all-extras          # Python deps (see table below)
./scripts/build-web.sh        # Dashboard → static/
```

**Offline / no API key:** leave `OPENROUTER_API_KEY` and `OLLAMA_API_KEY` unset and use defaults — agent boots in offline mode for local UI and tests.

---

### Python packages (from `pyproject.toml`)

Installed automatically with `uv sync`.

| Package | Role |
|---------|------|
| `fastapi`, `uvicorn` | HTTP API + dashboard backend |
| `openai`, `openai-agents` | Agent runtime, tools, sessions |
| `pydantic`, `pydantic-settings` | Config + `.env` |
| `httpx` | wabot client, web fetch, web-agent |
| `pyjwt[crypto]` | Optional Cloudflare Access JWT |
| `ddgs` | DuckDuckGo web search (no API key) |
| `faster-whisper` | Voice-note transcription |
| `pypdf` | PDF text extraction |
| `qrcode` | Pairing UI helpers |
| `mem0ai`, `fastembed` | Long-term memory (when enabled) |
| `composio`, `composio-openai-agents` | Composio tool router (when enabled) |

**Dev only** (`uv sync --all-extras`): `pytest`, `pytest-asyncio`, `ruff`, `pillow`.

---

### Frontend (`web/`)

| Package | Role |
|---------|------|
| React 18, Vite 5, TypeScript | Dashboard SPA |
| Tailwind CSS | Styling |
| Zustand | Client state |
| `@clerk/clerk-react` | Optional sign-in (needs `VITE_CLERK_PUBLISHABLE_KEY`) |

```bash
cd web && npm install && npm run build   # or npm run dev for HMR on :5173
```

---

### wabot (required external service)

[wabot](https://github.com/TeddyJubu/wabot) is **not** bundled. Run it on the same host, **loopback only**.

```bash
git clone https://github.com/TeddyJubu/wabot.git
cd wabot && ./scripts/install.sh
wa setup && wa doctor && wa health
```

**Agent `.env`:**

```dotenv
WABOT_ENDPOINT=http://127.0.0.1:7777
WABOT_TOKEN=...
WABOT_INBOUND_TOKEN=...
WABOT_AGENT_WABOT_HOME=/opt/wabot          # VPS: for /pair "New QR"
```

**wabot `.env` webhooks** (point at the agent, loopback in production):

```dotenv
WABOT_INBOUND_URL=http://127.0.0.1:8787/whatsapp/inbound
WABOT_RECEIPT_URL=http://127.0.0.1:8787/whatsapp/receipt
WABOT_PRESENCE_URL=http://127.0.0.1:8787/whatsapp/presence
WABOT_HISTORY_SYNC_URL=http://127.0.0.1:8787/whatsapp/history-sync
WABOT_HISTORY_URL=http://127.0.0.1:8787/whatsapp/history
```

Never expose wabot (`:7777`) on the public internet.

---

### LLM providers (pick one)

Set `WABOT_AGENT_MODEL_PROVIDER` in `.env`.

| Provider | Value | Credentials | Base URL | Notes |
|----------|--------|-------------|----------|--------|
| **ChatGPT / Codex** (default) | `codex` | `codex login` → `~/.codex/auth.json` | `CODEX_BASE_URL` | Uses your ChatGPT or Codex subscription |
| **OpenRouter** | `openrouter` | `OPENROUTER_API_KEY` | `OPENROUTER_BASE_URL` | Hosted models, credits |
| **Ollama (local)** | `ollama` | optional (`ollama`) | `OLLAMA_BASE_URL` | Default `http://127.0.0.1:11434/v1` |
| **Ollama Cloud** | `ollama_cloud` | `OLLAMA_API_KEY` | `OLLAMA_CLOUD_BASE_URL` | e.g. `gemma4:31b-cloud` → API id `gemma4:31b` |

```dotenv
# ChatGPT / Codex subscription (default)
WABOT_AGENT_MODEL_PROVIDER=codex
CODEX_MODEL=gpt-5.5
# Run: codex login
```

```dotenv
# Example: Ollama Cloud (common on VPS)
WABOT_AGENT_MODEL_PROVIDER=ollama_cloud
OLLAMA_API_KEY=...
OLLAMA_MODEL=gemma4:31b-cloud
```

**Vision** (inbound photos): use a vision-capable model (`gemma4`, `gpt-4o`, etc.) and `WABOT_AGENT_VISION_ATTACH_IMAGES=true`.

**Mem0** (if enabled): uses the same provider for fact extraction; embeddings use **FastEmbed** locally when on Ollama (Ollama Cloud has no `/v1/embeddings`). See [docs/mem0-setup.md](docs/mem0-setup.md).

---

### Optional: Mem0 long-term memory

| Dependency | Notes |
|------------|--------|
| `mem0ai`, `fastembed` | Python (in lockfile) |
| Local Qdrant path | `WABOT_AGENT_MEM0_PATH=./data/mem0_qdrant` |
| LLM for extraction | Same as chat provider (or OpenRouter when configured) |

```dotenv
WABOT_AGENT_MEM0_ENABLED=true
WABOT_AGENT_MEM0_AUTO_CAPTURE=true
WABOT_AGENT_MEM0_INJECT_ON_RUN=true
```

Memories are keyed to the **sender** (person), not only the group chat, so facts follow you across DMs and groups. Conversation history stays per chat thread.

---

### Optional: Composio (app integrations)

| Mode | Env | Docs |
|------|-----|------|
| **Native tools** (recommended) | `COMPOSIO_API_KEY` + `WABOT_AGENT_COMPOSIO_ENABLED=true` | [composio-setup.md](docs/composio-setup.md) |
| **Connect MCP** | `WABOT_AGENT_MCP_CONFIG=./configs/mcp.composio.json` | [composio-mcp-setup.md](docs/composio-mcp-setup.md) |

Get `COMPOSIO_API_KEY` from [platform.composio.dev](https://platform.composio.dev/settings). Standard `ak_` keys work for native tools; MCP Connect may need an **AI Clients** key from the dashboard.

Per-app OAuth (Gmail, etc.) happens via Composio tools — the agent sends you a link in chat to approve.

---

### Optional: Firecrawl deep research

| Component | Install |
|-----------|---------|
| **firecrawl-cli** | `npm install -g firecrawl-cli` + `firecrawl login` |
| **web-agent** sidecar | Clone [firecrawl/web-agent](https://github.com/firecrawl/web-agent), express template on `:3000` |
| **Keys** | `FIRECRAWL_API_KEY` + LLM for sidecar (`CUSTOM_OPENAI_*` or Google/Anthropic) |

```dotenv
FIRECRAWL_API_KEY=fc-...
WABOT_AGENT_WEB_AGENT_ENABLED=true
WABOT_AGENT_WEB_AGENT_URL=http://127.0.0.1:3000
```

Automated VPS setup: `SSH_HOST=your-host ./scripts/setup-firecrawl-vps.sh` (uses local Firecrawl credentials if `FIRECRAWL_API_KEY` is unset). Details: [docs/web-agent-setup.md](docs/web-agent-setup.md).

---

### Optional: MCP servers

Configure `WABOT_AGENT_MCP_CONFIG` (JSON). Example files:

| File | Purpose |
|------|---------|
| `configs/mcp.example.json` | Local stdio example (disabled) |
| `configs/mcp.composio.json` | Composio Connect HTTP MCP |

Headers support `${ENV_VAR}` expansion. Failed servers are dropped at startup (`drop_failed_servers`).

---

### Optional: Clerk (dashboard auth)

```bash
# web/.env (build time)
VITE_CLERK_PUBLISHABLE_KEY=pk_...
```

Without Clerk, use `/login` with `WABOT_AGENT_DASHBOARD_PASSWORD` or `WABOT_AGENT_OPERATOR_TOKEN`.

---

### VPS system packages (attachments)

For PDF, OCR, voice, and video on a server:

```bash
sudo APP_DIR=/opt/wabot-agent APP_USER=wabotagent \
  bash scripts/install-vps-processing-tools.sh
```

| Package | Used for |
|---------|----------|
| `ffmpeg`, `ffprobe` | Audio/video, voice notes |
| `poppler-utils` | `pdftotext`, `pdftoppm` |
| `tesseract-ocr` | Image / scanned PDF OCR |
| `file`, `unzip` | Type detection, archives |

`scripts/bootstrap-vps.sh` runs this when present. After deploy: `sudo systemctl restart wabot-agent`.

**RAM (8GB VPS):** Whisper `tiny` for strangers, `small` for owners (`WABOT_AGENT_WHISPER_MODEL` / `_OWNER`).

---

### Environment file map

Copy [`.env.example`](.env.example) → `.env`. High-signal groups:

| Section in `.env.example` | Guide section |
|---------------------------|---------------|
| `WABOT_AGENT_MODEL_PROVIDER` | [LLM providers](#llm-providers-pick-one) |
| `WABOT_AGENT_MEM0_*` | [Mem0](#optional-mem0-long-term-memory) |
| `COMPOSIO_*` | [Composio](#optional-composio-app-integrations) |
| `WABOT_AGENT_WEB_AGENT_*` | [Firecrawl](#optional-firecrawl-deep-research) |
| `WABOT_*` / `WABOT_AGENT_WABOT_*` | [wabot](#wabot-required-external-service) |
| `WABOT_AGENT_FILE_*`, `WHISPER_*` | [VPS system packages](#vps-system-packages-attachments) |
| `WABOT_AGENT_CF_ACCESS_*` | [Operator authentication](#operator-authentication) |

---

## Quickstart (local)

```bash
uv sync --all-extras
cp .env.example .env
# Edit .env: at minimum wabot tokens; add OPENROUTER_API_KEY or OLLAMA_API_KEY for live model
./scripts/build-web.sh
uv run python main.py
```

Open [http://127.0.0.1:8787/login](http://127.0.0.1:8787/login).

**Frontend HMR:**

```bash
cd web && npm install && npm run dev    # http://127.0.0.1:5173
uv run python main.py                   # http://127.0.0.1:8787
```

Vite proxies `/api`, `/whatsapp`, `/health`, and `/ready` to FastAPI.

---

## Distribution

```bash
chmod +x scripts/package-release.sh scripts/install-from-release.sh
./scripts/package-release.sh
# → dist/wabot-agent-0.1.0.tar.gz + .sha256
```

Recipients follow [DISTRIBUTION.md](DISTRIBUTION.md). Package a branch with `REF=my-version ./scripts/package-release.sh`.

---

## Operator authentication

| Layer | Purpose |
|--------|---------|
| **`/login`** | `WABOT_AGENT_DASHBOARD_PASSWORD` or operator token → 30-day cookie |
| **`WABOT_AGENT_OPERATOR_TOKEN`** | `X-Operator-Token` / `Authorization: Bearer` for API |
| **Cloudflare Access** | Optional; `WABOT_AGENT_CF_ACCESS_REQUIRED=true` |

Legacy: `https://your-host/?token=<operator-token>` once.

---

## Send policy

```dotenv
WABOT_AGENT_SEND_POLICY=dry_run     # dry_run | owner | allowlist | allow_all
WABOT_AGENT_OWNER_NUMBERS=+15551234567
WABOT_AGENT_ALLOWED_RECIPIENTS=1234567890@lid
```

Production defaults:

```bash
uv run python scripts/apply-production-hygiene.py
./scripts/check-production-hygiene.sh
```

---

## Production VPS

1. **Bootstrap:** `sudo APP_DIR=/opt/wabot-agent APP_USER=wabotagent ./scripts/bootstrap-vps.sh`
2. **Configure:** `/opt/wabot-agent/.env` and `/opt/wabot/wabot.env`
3. **Deploy:** `SSH_HOST=your-host APP_DIR=/opt/wabot-agent ./scripts/deploy-to-vignesh.sh`
4. **HTTPS:** Caddy or Cloudflare → `127.0.0.1:8787` only (not wabot `:7777`)
5. **Pairing:** `/login` → `/pair` → add owner numbers or JIDs before enabling live sends

`deploy-to-vignesh.sh` rsyncs code into `/opt/wabot-agent`; the VPS directory is not a git
checkout and deploys intentionally do not overwrite `.env` or `data/`. After deploy, verify
`systemctl is-active wabot-agent wabot`, authenticated `/ready`, and the reported send policy.

Optional: [Cloudflare Tunnel + Access](docs/superpowers/specs/2026-05-15-public-pairing-website-design.md) via `scripts/setup-cloudflared.sh`.

---

## HTTP API (summary)

```text
GET   /health
GET   /login
POST  /api/auth/login
GET   /ready                          # operator auth
GET   /api/whatsapp/pairing
POST  /api/chat
POST  /api/chat/stream
GET   /api/stream                     # SSE
POST  /whatsapp/inbound               # wabot webhook (Bearer)
```

Full webhook shape and routes: see existing operator docs in `src/wabot_agent/api.py`.

---

## Context management

- Session window: `WABOT_AGENT_SESSION_HISTORY_LIMIT` (default 48 turns)
- Token budget: `WABOT_AGENT_SESSION_MAX_HISTORY_TOKENS`
- Pruning + LLM summaries: `thread_summary.py`, `context_management.py`

---

## Verification

```bash
uv run ruff check .
uv run pytest -q -m "not live"
uv run python evals/run_local.py
cd web && npm run test -- --run && npm run build
./scripts/verify-phase1.sh    # with wabot running; or SKIP_LIVE=1
```

---

## Repository layout

```text
src/wabot_agent/     # FastAPI, agent, tools, memory, Mem0, Composio
web/                 # React dashboard (Vite)
static/              # Built SPA
configs/             # MCP JSON (example, composio)
scripts/             # deploy, hygiene, firecrawl, build-web
deploy/              # systemd, cloudflared examples
skills/              # Local agent skills
docs/                # mem0, composio, web-agent, architecture
tests/               # Offline pytest
```

---

## Further reading

| Topic | Doc |
|-------|-----|
| Mem0 | [docs/mem0-setup.md](docs/mem0-setup.md) |
| Composio native | [docs/composio-setup.md](docs/composio-setup.md) |
| Composio MCP | [docs/composio-mcp-setup.md](docs/composio-mcp-setup.md) |
| Firecrawl | [docs/web-agent-setup.md](docs/web-agent-setup.md) |
| Roadmap | [plan.md](plan.md) |

---

## License

[MIT License](LICENSE) — Copyright (c) 2026 TeddyJubu and contributors.

## Contributing

[CONTRIBUTING.md](CONTRIBUTING.md)

## Safety

- Keep `.env`, `data/`, tokens, and keys out of git.
- wabot on loopback; only the agent UI is public HTTPS.
- Use allowlists in production; rotate secrets if exposed in chat or logs.
