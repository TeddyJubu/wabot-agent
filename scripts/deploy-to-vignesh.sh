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

ssh "$SSH_HOST" "cd '$APP_DIR' && uv sync --all-extras && sudo systemctl restart wabot-agent && sudo systemctl status wabot-agent --no-pager"

