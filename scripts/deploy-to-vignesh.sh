#!/usr/bin/env bash
set -euo pipefail

SSH_HOST="${SSH_HOST:-vignesh}"
APP_DIR="${APP_DIR:-/opt/wabot-agent}"

# Build the React SPA into static/ before rsyncing.
"$(dirname "$0")/build-web.sh"

rsync -az --delete \
  --exclude 'web/node_modules/' \
  --exclude 'web/dist/' \
  --exclude '.git' \
  --exclude '.venv/' \
  --exclude '.env' \
  --exclude 'data/' \
  --exclude '__pycache__/' \
  ./ "$SSH_HOST:$APP_DIR/"

# APP_DIR is passed as $1 (not interpolated) to prevent remote injection if it contains shell-meta chars.
APP_DIR_Q=$(printf '%q' "$APP_DIR")
ssh "$SSH_HOST" bash -l -s -- "$APP_DIR_Q" <<'REMOTE'
set -euo pipefail
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/home/linuxbrew/.linuxbrew/bin:$PATH"
cd -- "$1"
uv sync --all-extras
mkdir -p "$1/data/codex" "$1/data/mem0" "$1/data/composio"
sudo chown -R wabotagent:wabotagent "$1/data" 2>/dev/null || true
# App root may be owned by the deploy user; ensure the service account can write caches.
sudo chown wabotagent:wabotagent "$1" 2>/dev/null || true
sudo systemctl restart wabot-agent
sudo systemctl status wabot-agent --no-pager
REMOTE

