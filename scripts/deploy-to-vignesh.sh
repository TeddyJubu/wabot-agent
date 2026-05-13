#!/usr/bin/env bash
set -euo pipefail

SSH_HOST="${SSH_HOST:-vignesh}"
APP_DIR="${APP_DIR:-/opt/wabot-agent}"

rsync -az --delete \
  --exclude '.git' \
  --exclude '.venv/' \
  --exclude '.env' \
  --exclude 'data/' \
  --exclude '__pycache__/' \
  ./ "$SSH_HOST:$APP_DIR/"

# Wrap the remote command in `bash -lc` so profile files are sourced and `uv`
# (installed under ~/.local/bin or /usr/local/bin) is on PATH for non-interactive ssh.
# Pass APP_DIR as a remote env var (printf %q-escaped) rather than splicing it
# into the command string, so shell metacharacters in APP_DIR are treated as
# data on the remote, not as code. `cd --` guards against paths starting with `-`.
ssh "$SSH_HOST" "APP_DIR=$(printf '%q' "$APP_DIR") bash -lc 'export PATH=\$HOME/.local/bin:/usr/local/bin:\$PATH && cd -- \"\$APP_DIR\" && uv sync --all-extras && sudo systemctl restart wabot-agent && sudo systemctl status wabot-agent --no-pager'"

