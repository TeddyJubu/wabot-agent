#!/usr/bin/env bash
set -euo pipefail

SSH_HOST="${SSH_HOST:-vignesh}"
APP_DIR="${APP_DIR:-/opt/wabot-agent}"

rsync -az --delete \
  --exclude '.git/' \
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
sudo systemctl restart wabot-agent
sudo systemctl status wabot-agent --no-pager
REMOTE

