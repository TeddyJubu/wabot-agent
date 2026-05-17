#!/usr/bin/env bash
# Install wabot-agent from an unpacked release tarball or git checkout.
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$APP_DIR"

if [[ ! -f pyproject.toml ]] || [[ ! -f main.py ]]; then
  echo "Run this script from the wabot-agent project root (unpacked tarball or clone)." >&2
  exit 1
fi

UV_BIN="${UV_BIN:-}"
if [[ -z "$UV_BIN" ]]; then
  if command -v uv >/dev/null 2>&1; then
    UV_BIN="$(command -v uv)"
  elif [[ -x /usr/local/bin/uv ]]; then
    UV_BIN=/usr/local/bin/uv
  else
    echo "uv is required. Install: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
    exit 1
  fi
fi

if [[ ! -f static/index.html ]]; then
  if command -v npm >/dev/null 2>&1 && [[ -f web/package.json ]]; then
    echo "Building dashboard (static/) ..."
    bash "$APP_DIR/scripts/build-web.sh"
  else
    echo "Warning: static/index.html missing and npm unavailable; dashboard may be broken." >&2
  fi
fi

echo "Installing Python dependencies with uv ..."
"$UV_BIN" sync --directory "$APP_DIR" --frozen

if [[ ! -f .env ]]; then
  cp .env.example .env
  chmod 600 .env 2>/dev/null || true
  echo "Created .env from .env.example — edit before starting."
else
  echo "Keeping existing .env"
fi

mkdir -p data

echo ""
echo "Next steps:"
echo "  1. Edit .env (OPENROUTER_API_KEY, WABOT_TOKEN, WABOT_INBOUND_TOKEN, send policy)"
echo "  2. Install and pair wabot on this host (see DISTRIBUTION.md)"
echo "  3. Start: uv run python main.py"
echo "  4. VPS: sudo APP_DIR=$APP_DIR bash scripts/bootstrap-vps.sh"
echo ""
echo "Docs: DISTRIBUTION.md"
