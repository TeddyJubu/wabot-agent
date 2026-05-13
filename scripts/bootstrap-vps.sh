#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/vignesh-agent}"
APP_USER="${APP_USER:-vignesh}"
REPO_URL="${REPO_URL:-https://github.com/TeddyJubu/vignesh.git}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root on the VPS: sudo APP_DIR=$APP_DIR $0"
  exit 1
fi

apt-get update
apt-get install -y curl git rsync python3 ca-certificates

if ! id "$APP_USER" >/dev/null 2>&1; then
  useradd --system --create-home --shell /usr/sbin/nologin "$APP_USER"
fi

if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  install -m 0755 "$HOME/.local/bin/uv" /usr/local/bin/uv
fi

if [[ ! -d "$APP_DIR/.git" ]]; then
  git clone "$REPO_URL" "$APP_DIR"
else
  git -C "$APP_DIR" pull --ff-only
fi

mkdir -p "$APP_DIR/data" "$APP_DIR/.uv-cache"
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

if [[ ! -f "$APP_DIR/.env" ]]; then
  install -m 0600 -o "$APP_USER" -g "$APP_USER" "$APP_DIR/.env.example" "$APP_DIR/.env"
  echo "Created $APP_DIR/.env. Fill OPENROUTER_API_KEY, WABOT_TOKEN, and policy values."
fi

install -m 0644 "$APP_DIR/deploy/systemd/vignesh-agent.service" \
  /etc/systemd/system/vignesh-agent.service
systemctl daemon-reload
systemctl enable vignesh-agent.service

echo "Bootstrap complete. Edit $APP_DIR/.env, then run:"
echo "  sudo systemctl restart vignesh-agent"
echo "  sudo journalctl -u vignesh-agent -f"
