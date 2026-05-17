# Distributing wabot-agent

**wabot-agent** is open source ([MIT License](LICENSE)). You may copy, modify, and redistribute it under those terms.

This guide is for operators who receive a **release tarball** or clone the repo to run their own WhatsApp agent (not the author's VPS).

## What you need

| Component | Role |
|-----------|------|
| **wabot-agent** (this project) | FastAPI control plane, LLM agent, dashboard, webhooks on `:8787` |
| **[wabot](https://github.com/TeddyJubu/wabot)** | WhatsApp bridge (whatsmeow) on loopback `:7777` — separate install |
| **LLM API** | OpenRouter, Ollama Cloud, or local Ollama (see `.env.example`) |
| **Host** | Linux VPS recommended; macOS works for local dev |

System tools for attachments (optional but recommended on a VPS): `ffmpeg`, `tesseract-ocr`, `poppler-utils`. Install via:

```bash
sudo APP_DIR=/opt/wabot-agent bash scripts/install-vps-processing-tools.sh
```

## Option A — Release tarball (no git)

Someone with the repo builds:

```bash
./scripts/package-release.sh
# Optional: package a specific branch/tag
REF=my-version ./scripts/package-release.sh
```

Share **`dist/wabot-agent-<version>.tar.gz`** and **`dist/wabot-agent-<version>.tar.gz.sha256`**.

Recipient:

```bash
tar xzf wabot-agent-0.1.0.tar.gz
cd wabot-agent-0.1.0
chmod +x scripts/install-from-release.sh
./scripts/install-from-release.sh
```

Then configure `.env` and install **wabot** (below).

## Option B — Git clone

```bash
git clone https://github.com/TeddyJubu/wabot-agent.git
cd wabot-agent
git checkout my-version   # or main
./scripts/install-from-release.sh
```

## Configure wabot (required)

On the **same machine** as the agent:

```bash
git clone https://github.com/TeddyJubu/wabot.git
cd wabot && ./scripts/install.sh
wa setup && wa doctor && wa health
```

In **wabot** config, point webhooks at the agent (loopback only in production):

```dotenv
WABOT_INBOUND_URL=http://127.0.0.1:8787/whatsapp/inbound
WABOT_RECEIPT_URL=http://127.0.0.1:8787/whatsapp/receipt
WABOT_PRESENCE_URL=http://127.0.0.1:8787/whatsapp/presence
WABOT_HISTORY_SYNC_URL=http://127.0.0.1:8787/whatsapp/history-sync
WABOT_HISTORY_URL=http://127.0.0.1:8787/whatsapp/history
```

In **wabot-agent** `.env`:

```dotenv
WABOT_ENDPOINT=http://127.0.0.1:7777
WABOT_TOKEN=<same as wabot>
WABOT_INBOUND_TOKEN=<shared secret for webhooks>
OPENROUTER_API_KEY=<your key>
WABOT_AGENT_SEND_POLICY=allowlist
WABOT_AGENT_ALLOWED_RECIPIENTS=<your WhatsApp JIDs>
WABOT_AGENT_AUTO_REPLY=true
WABOT_AGENT_TYPING_INDICATOR=true
```

Never expose wabot `:7777` on the public internet. Put HTTPS in front of **only** `:8787` (Caddy, Cloudflare Tunnel, etc.) if you need remote dashboard/pairing.

## Run locally

```bash
uv run python main.py
```

Open `http://127.0.0.1:8787/login` and pair WhatsApp at `/pair`.

## Run on a VPS (systemd)

```bash
sudo APP_DIR=/opt/wabot-agent APP_USER=wabotagent \
  bash scripts/bootstrap-vps.sh
```

Edit `/opt/wabot-agent/.env`, then:

```bash
sudo systemctl restart wabot-agent
sudo systemctl status wabot-agent
```

Production hygiene:

```bash
uv run python scripts/apply-production-hygiene.py
./scripts/check-production-hygiene.sh
```

## Security checklist for recipients

- Do **not** ship `.env`, `data/*.db`, `runtime_overrides.json` with secrets, or wabot `store.db`.
- Start with `WABOT_AGENT_SEND_POLICY=allowlist` or `dry_run`, not `allow_all`.
- Set `WABOT_AGENT_DASHBOARD_PASSWORD` or `WABOT_AGENT_OPERATOR_TOKEN` before exposing the dashboard.
- Rotate `WABOT_INBOUND_TOKEN` if the tarball or logs may have leaked.

## Updating

**Tarball installs:** unpack a new version over `APP_DIR` (keep `.env` and `data/`), run `./scripts/install-from-release.sh`, restart the service.

**Git installs:** `git pull && ./scripts/install-from-release.sh && sudo systemctl restart wabot-agent`

## Version

Package version is defined in `pyproject.toml` (`project.version`). Release archives are named `wabot-agent-<version>.tar.gz`.

## License

Include the bundled `LICENSE` file when you redistribute source or binaries. Do not remove copyright or permission notices.
