#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/wabot-agent}"
APP_USER="${APP_USER:-wabotagent}"
REPO_URL="${REPO_URL:-https://github.com/TeddyJubu/wabot-agent.git}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root on the VPS: sudo APP_DIR=$APP_DIR $0"
  exit 1
fi

apt-get update
apt-get install -y curl git rsync python3 ca-certificates

if ! id "$APP_USER" >/dev/null 2>&1; then
  useradd --system --create-home --shell /usr/sbin/nologin "$APP_USER"
fi

# Canonical uv location is /usr/local/bin/uv so it lands in sudo's secure_path
# for the `sudo -u "$APP_USER" uv sync ...` call below. Gate on the absolute
# path, not `command -v uv`, so a stray uv on root's PATH (e.g. /root/.local/bin)
# doesn't cause us to skip the install-to-system-path step.
if [[ ! -x /usr/local/bin/uv ]]; then
  if ! command -v uv >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
  fi
  install -m 0755 "$(command -v uv)" /usr/local/bin/uv
fi
UV_BIN=/usr/local/bin/uv

if [[ ! -d "$APP_DIR/.git" ]]; then
  git clone "$REPO_URL" "$APP_DIR"
else
  git -C "$APP_DIR" pull --ff-only
fi

mkdir -p "$APP_DIR/data" "$APP_DIR/.uv-cache"
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

# Invoke uv by absolute path: `uv --version` as root would otherwise mask the
# case where $APP_USER's sudo secure_path can't reach uv. Using $UV_BIN gives
# both calls the same lookup path, so the smoke check actually exercises what
# `uv sync` will see.
"$UV_BIN" --version
sudo -u "$APP_USER" UV_CACHE_DIR="$APP_DIR/.uv-cache" \
  "$UV_BIN" sync --directory "$APP_DIR" --frozen --all-extras

if [[ ! -f "$APP_DIR/.env" ]]; then
  install -m 0600 -o "$APP_USER" -g "$APP_USER" "$APP_DIR/.env.example" "$APP_DIR/.env"
  echo "Created $APP_DIR/.env. Fill OPENROUTER_API_KEY, WABOT_TOKEN, and policy values."
fi

install -m 0644 "$APP_DIR/deploy/systemd/wabot-agent.service" \
  /etc/systemd/system/wabot-agent.service
systemctl daemon-reload
systemctl enable wabot-agent.service

# Smoke check: confirm systemd parsed the unit file. Non-zero exit if the unit
# is missing or malformed — fail loudly here rather than at first `start`.
systemctl cat wabot-agent.service > /dev/null

echo "Bootstrap complete. Edit $APP_DIR/.env, then run:"
echo "  sudo systemctl restart wabot-agent"
echo "  sudo journalctl -u wabot-agent -f"
