# wabot-agent

wabot-agent is a VPS-ready WhatsApp automation agent built around the OpenAI Agents SDK, OpenRouter, and [`wabot`](https://github.com/TeddyJubu/wabot). It is designed to run locally first, then upload cleanly to the SSH host named `vignesh`.

![Architecture](docs/agent-interactions.png)

## What It Does

- Runs an Agents SDK agent behind a FastAPI service.
- Uses OpenRouter through the OpenAI-compatible Chat Completions API.
- Treats `wabot` as the primary side-effect tool for WhatsApp.
- Keeps durable local memory in SQLite: contact facts, agent notes, processed inbound ids, runs, and tool events.
- Supports local skills under `skills/*/SKILL.md`.
- Supports optional MCP servers through `WABOT_AGENT_MCP_CONFIG`.
- Exposes a small operator dashboard at `/`.
- Defaults to `dry_run` send policy so fresh installs cannot send WhatsApp messages by accident.

## Architecture

![Inbound sequence](docs/agent-sequence.png)

The model can plan and choose tools, but the Python harness owns execution. WhatsApp sends go through a narrow `wabot` client that checks send policy and daemon readiness before calling `/send` or `/send-image`.

The FastAPI backend serves a local React SPA (Vite + TypeScript, source in `web/`, built into `static/`) rather than a hosted Agent Builder or Vercel-first UI because the critical dependency is a loopback-only `wabot` daemon on the VPS. That keeps WhatsApp session state, tokens, and send authorization close to the host that owns them. A Vercel or AgentKit frontend can still be added later against this API if you want a hosted operator surface.

```text
Operator / wabot inbound webhook
  -> FastAPI control plane
  -> Agents SDK runner
  -> OpenRouter model
  -> guarded tools
  -> local wabot daemon
  -> WhatsApp linked device
```

## Local Quickstart

```bash
uv sync --all-extras
cp .env.example .env
./scripts/build-web.sh        # builds the React SPA into static/
uv run python main.py
```

Open [http://127.0.0.1:8787](http://127.0.0.1:8787).

With no `OPENROUTER_API_KEY`, the service runs in offline mode. This is intentional: the app can boot, render, and test without network credentials.

### Frontend dev (HMR)

The operator dashboard is a React SPA in `web/`. For hot module reload while developing:

```bash
cd web && npm install         # one-time
cd web && npm run dev         # Vite at http://127.0.0.1:5173
# in another terminal:
uv run python main.py         # FastAPI at http://127.0.0.1:8787
```

Vite proxies `/api`, `/whatsapp`, `/health`, and `/ready` back to FastAPI on 8787.

To ship a fresh build into the static bundle (also called by `deploy-to-vignesh.sh`):

```bash
./scripts/build-web.sh
```

## Connect OpenRouter

Edit `.env`:

```bash
OPENROUTER_API_KEY=...
OPENROUTER_MODEL=openai/gpt-5.2
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
```

Secrets stay in `.env`, which is ignored by git. Do not paste OpenRouter keys into chat prompts, skills, memory, README files, or MCP config.

The current environment prefix is `WABOT_AGENT_*`. Existing `VIGNESH_*` variables are still accepted as backward-compatible aliases during migration.

## Connect WhatsApp

`wabot` uses the WhatsApp Web linked-device protocol through `whatsmeow`. It does not automate the browser tab at `web.whatsapp.com`; it creates a linked device that your phone can remove at any time from WhatsApp settings.

The dashboard includes a WhatsApp linking panel. With a recent `wabot` daemon, open `/`, scan the QR shown under **WhatsApp Link**, and wait for readiness to switch to connected.

Install and pair `wabot` first when bootstrapping manually:

```bash
git clone https://github.com/TeddyJubu/wabot.git
cd wabot
./scripts/install.sh --prefix /usr/local
wa setup
wa doctor
wa health
```

The agent expects:

```bash
WABOT_ENDPOINT=http://127.0.0.1:7777
WABOT_TOKEN=...
WABOT_TOKEN_FILE=~/.config/wabot/token
WABOT_INBOUND_TOKEN=...
```

Use `WABOT_HTTP_ADDR=127.0.0.1:7777` for the daemon. Do not expose the wabot daemon directly to the public internet.

Older `wabot` builds only print QR codes to stdout or `journalctl -u wabot -f`. Upgrade `wabot` if the dashboard says `/pairing/qr` is unavailable.

## Send Policy

The default is safe:

```bash
WABOT_AGENT_SEND_POLICY=dry_run
```

Production recommendation:

```bash
WABOT_AGENT_SEND_POLICY=allowlist
WABOT_AGENT_ALLOWED_RECIPIENTS=+15550001111,+15550002222
WABOT_AGENT_OPERATOR_TOKEN=<long-random-dashboard-token>
```

`allow_all` exists for controlled environments, but it removes the recipient guard. Use it deliberately.

When `WABOT_AGENT_OPERATOR_TOKEN` is set, open the dashboard once with:

```text
http://127.0.0.1:8787/?token=<long-random-dashboard-token>
```

The service stores that token in an HTTP-only same-site cookie for same-origin dashboard calls. Direct API callers can use either `X-Operator-Token` or `Authorization: Bearer ...`.

## HTTP API

```text
GET   /health
GET   /ready
GET   /api/whatsapp/pairing
GET   /api/whatsapp/pairing.svg
POST  /api/chat
POST  /api/chat/stream              # NDJSON delta/tool_call/tool_result/final events
GET   /api/stream                   # SSE event hub (pairing, runs, settings deltas)
GET   /api/runs
GET   /api/memory/{contact}
GET   /api/settings
PATCH /api/settings
POST  /api/settings/test/openrouter
POST  /api/settings/test/wabot
POST  /whatsapp/inbound
```

Inbound webhook payload from `wabot`:

```json
{
  "id": "message-id",
  "timestamp": "2026-05-13T12:00:00Z",
  "from": "+15550001111",
  "chat": "+15550001111",
  "is_group": false,
  "push_name": "wabot-agent",
  "text": "hello"
}
```

If `WABOT_INBOUND_TOKEN` is set, `/whatsapp/inbound` requires:

```text
Authorization: Bearer <WABOT_INBOUND_TOKEN>
```

Inbound messages are deduped by `id`.

## Tools

The core tool set is intentionally narrow:

- `wabot_health`
- `send_whatsapp_text`
- `send_whatsapp_image`
- `recall_contact_memory`
- `remember_contact_fact`
- `recall_agent_notes`
- `remember_agent_note`
- `list_local_skills`
- `read_local_skill`

Tool results and logs are redacted before persistence.

Image sends are confined to `WABOT_AGENT_MEDIA_DIR` (`./data/media` by default). Put approved outbound media there before asking the agent to send it.

## Skills And MCP

Local skills live in:

```text
skills/<name>/SKILL.md
```

MCP servers are configured by JSON:

```bash
WABOT_AGENT_MCP_CONFIG=./configs/mcp.example.json
```

Every example MCP server is disabled by default. Enable only trusted servers and keep privileged tools behind approval or an allowlist.

## VPS Deployment

On the VPS:

```bash
sudo APP_DIR=/opt/wabot-agent APP_USER=wabotagent ./scripts/bootstrap-vps.sh
sudo nano /opt/wabot-agent/.env
sudo systemctl restart wabot-agent
sudo journalctl -u wabot-agent -f
```

From this local machine after the VPS is bootstrapped:

```bash
SSH_HOST=vignesh ./scripts/deploy-to-vignesh.sh
```

The systemd unit is in `deploy/systemd/wabot-agent.service`.

## Public Access (Optional)

To pair WhatsApp from any phone or laptop browser — without SSHing into the VPS — run the Cloudflare Tunnel installer:

```bash
sudo ./scripts/setup-cloudflared.sh wabot.your-domain.com
```

This installs `cloudflared`, creates a tunnel from the VPS to Cloudflare's edge, routes DNS to it, and starts a systemd service. **No inbound ports are opened on the VPS.** `wabot` stays on loopback. The script prints the manual steps to add a Cloudflare Access policy (Google login or one-time-PIN email), after which you set three env vars in `.env`:

```dotenv
WABOT_AGENT_CF_ACCESS_TEAM_DOMAIN=<yourteam>.cloudflareaccess.com
WABOT_AGENT_CF_ACCESS_AUD=<Application Audience tag from CF dashboard>
WABOT_AGENT_CF_ACCESS_REQUIRED=true
```

Open `https://wabot.<your-domain>/pair` on a phone — sign in through Access, scan the QR with WhatsApp, done. The QR re-renders live as `wabot` rotates the pairing code (SSE-driven).

See [docs/superpowers/specs/2026-05-15-public-pairing-website-design.md](docs/superpowers/specs/2026-05-15-public-pairing-website-design.md) for the full design, threat model, and what's intentionally NOT included (accounts, per-user instances, billing — those are future sub-projects).

## Verification

Offline checks:

```bash
uv run --with '.[dev]' ruff check .
uv run --with '.[dev]' python -m pytest -q
uv run python evals/run_local.py
```

Credentialed smoke checks, when the VPS is ready:

```bash
curl -fsS http://127.0.0.1:8787/health
curl -fsS http://127.0.0.1:8787/ready
wa doctor
wa health
```

Then use the dashboard to ask for a health check and a draft response before enabling real sends.

## Continuous Integration

Every push and pull request runs [`.github/workflows/ci.yml`](.github/workflows/ci.yml) with three jobs:

- **backend** — `uv sync --all-extras`, `ruff check .`, `pytest -m "not live"` (offline tests).
- **evals** — the local eval harness at [`evals/run_local.py`](evals/run_local.py).
- **web** — Vitest unit tests and the production Vite build.

The uv tool cache is keyed on `uv.lock`, the npm cache on `web/package-lock.json`; warm re-runs install in seconds.

Pull requests into `main` must clear **all three checks** and **one approving review** before merge, and linear history is enforced — rebase onto `main` rather than merging it back in. To reproduce the gates locally, run the [offline checks](#verification) and:

```bash
cd web && npm run test -- --run && npm run build
```

## Repository Layout

```text
src/wabot_agent/
  agent.py          # Agents SDK orchestration
  api.py            # FastAPI app and webhook surface
  models.py         # OpenRouter and offline model wiring
  tools.py          # Agent tools and send policy checks
  memory.py         # SQLite memory and idempotency
  wabot.py          # HTTP client for wabot
  ui_envelopes.py   # Polished tool-result UI envelopes for the SPA
web/                # React SPA source (Vite + TypeScript + Tailwind)
static/             # Built React SPA (auto-generated by scripts/build-web.sh)
skills/             # Local agent skills
configs/            # MCP config examples
deploy/             # systemd assets
scripts/            # VPS + build-web.sh + diagram helpers
tests/              # Offline Python test suite
evals/              # Local eval harness
docs/               # Architecture diagrams, prompt notes, specs/plans
```

## Safety Notes

- Keep `.env`, `store.db`, `wabot.env`, and `sends.log` out of git.
- Back up `store.db`; it is the WhatsApp linked-device identity.
- Treat `logged_in=false` or `connected=false` as an operational incident.
- Keep `wabot` bound to loopback.
- Use allowlists for production sending.
- Rotate secrets if they ever appear in prompts, logs, memory, traces, or screenshots.
