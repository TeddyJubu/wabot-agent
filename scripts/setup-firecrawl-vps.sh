#!/usr/bin/env bash
# Install Firecrawl CLI + web-agent express sidecar on the VPS and enable wabot-agent integration.
set -euo pipefail

SSH_HOST="${SSH_HOST:-vignesh}"
APP_DIR="${APP_DIR:-/opt/wabot-agent}"
WEB_AGENT_DIR="${WEB_AGENT_DIR:-/opt/web-agent}"
SERVICE_USER="${SERVICE_USER:-wabotagent}"

if [[ -z "${FIRECRAWL_API_KEY:-}" ]]; then
  CREDS="${HOME}/Library/Application Support/firecrawl-cli/credentials.json"
  if [[ -f "$CREDS" ]]; then
    FIRECRAWL_API_KEY="$(python3 -c "import json; print(json.load(open('$CREDS'))['apiKey'])")"
  fi
fi
if [[ -z "${FIRECRAWL_API_KEY:-}" ]]; then
  echo "Set FIRECRAWL_API_KEY or run 'firecrawl login' locally first." >&2
  exit 1
fi

FC_KEY_Q=$(printf '%q' "$FIRECRAWL_API_KEY")
ssh "$SSH_HOST" bash -s -- "$WEB_AGENT_DIR" "$APP_DIR" "$SERVICE_USER" "$FC_KEY_Q" <<'REMOTE'
set -euo pipefail
WEB_AGENT_DIR="$1"
APP_DIR="$2"
SERVICE_USER="$3"
FIRECRAWL_API_KEY="$4"

export PATH="/usr/bin:/usr/local/bin:$PATH"

if ! command -v node >/dev/null; then
  echo "node is required on the VPS" >&2
  exit 1
fi

sudo npm install -g firecrawl-cli

if [[ ! -d "$WEB_AGENT_DIR/.git" ]]; then
  sudo git clone --depth 1 https://github.com/firecrawl/web-agent.git "$WEB_AGENT_DIR"
  sudo chown -R "$SERVICE_USER:$SERVICE_USER" "$WEB_AGENT_DIR"
fi

EXPRESS_DIR="$WEB_AGENT_DIR/agent-templates/express"
cd "$EXPRESS_DIR"
sudo -u "$SERVICE_USER" npm install

OLLAMA_API_KEY=""
if [[ -f "$APP_DIR/.env" ]]; then
  OLLAMA_API_KEY="$(grep -E '^OLLAMA_API_KEY=' "$APP_DIR/.env" | cut -d= -f2- || true)"
fi

sudo -u "$SERVICE_USER" tee "$EXPRESS_DIR/.env" >/dev/null <<ENV
FIRECRAWL_API_KEY=${FIRECRAWL_API_KEY}
MODEL=custom-openai:gemma4:31b
CUSTOM_OPENAI_API_KEY=${OLLAMA_API_KEY:-ollama}
CUSTOM_OPENAI_BASE_URL=https://ollama.com/v1
PORT=3000
ENV
chmod 600 "$EXPRESS_DIR/.env"

sudo -u "$SERVICE_USER" npm run doctor

sudo tee /etc/systemd/system/firecrawl-web-agent.service >/dev/null <<UNIT
[Unit]
Description=Firecrawl web-agent (express sidecar)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${SERVICE_USER}
Group=${SERVICE_USER}
WorkingDirectory=${EXPRESS_DIR}
EnvironmentFile=${EXPRESS_DIR}/.env
ExecStart=$(command -v npm) start
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable firecrawl-web-agent
sudo systemctl restart firecrawl-web-agent

python3 <<PY
import re
from pathlib import Path

app_env = Path("$APP_DIR") / ".env"
text = app_env.read_text() if app_env.exists() else ""
updates = {
    "FIRECRAWL_API_KEY": "$FIRECRAWL_API_KEY",
    "WABOT_AGENT_WEB_AGENT_ENABLED": "true",
    "WABOT_AGENT_WEB_AGENT_URL": "http://127.0.0.1:3000",
    "WABOT_AGENT_WEB_AGENT_TIMEOUT_SEC": "7200",
    "WABOT_AGENT_WEB_AGENT_MAX_CONCURRENT": "1",
    "WABOT_AGENT_WEB_AGENT_MAX_PENDING_PER_CONTACT": "3",
    "WABOT_AGENT_WEB_AGENT_OWNER_ONLY": "true",
    "WABOT_AGENT_WEB_AGENT_NOTIFY_ON_COMPLETE": "true",
}
for key, value in updates.items():
    pat = rf"^{re.escape(key)}=.*$"
    line = f"{key}={value}"
    text = re.sub(pat, line, text, flags=re.M) if re.search(pat, text, flags=re.M) else text.rstrip() + "\n" + line + "\n"
app_env.write_text(text)
PY

sudo systemctl restart wabot-agent
sleep 3
curl -fsS http://127.0.0.1:3000/ | head -c 400
echo ""
systemctl is-active firecrawl-web-agent wabot-agent
REMOTE

echo "Firecrawl web-agent setup complete on $SSH_HOST"
