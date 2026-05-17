#!/usr/bin/env bash
# Install lightweight system packages for wabot-agent file processing on Ubuntu VPS.
# Run on the server: sudo bash scripts/install-vps-processing-tools.sh
set -euo pipefail

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "Run as root: sudo bash $0" >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y --no-install-recommends \
  ffmpeg \
  poppler-utils \
  tesseract-ocr \
  tesseract-ocr-eng \
  file \
  unzip

echo "Installed:"
for cmd in ffmpeg ffprobe pdftotext pdfinfo tesseract file unzip; do
  if command -v "$cmd" >/dev/null 2>&1; then
    echo "  ok  $cmd -> $(command -v "$cmd")"
  else
    echo "  MISSING $cmd" >&2
  fi
done

echo "Done. Restart wabot-agent after deploying Python changes (faster-whisper)."

# Optional: preload Whisper models for the service user (avoids first-message delay).
if [[ -n "${APP_USER:-}" ]] && id "$APP_USER" >/dev/null 2>&1 && [[ -d "${APP_DIR:-/opt/wabot-agent}" ]]; then
  APP_DIR="${APP_DIR:-/opt/wabot-agent}"
  echo "Preloading faster-whisper tiny + base for $APP_USER ..."
  sudo -u "$APP_USER" env HOME="/home/$APP_USER" PATH="/home/$APP_USER/.local/bin:/usr/local/bin:$PATH" \
    bash -c "cd '$APP_DIR' && uv run python -c \"
from faster_whisper import WhisperModel
for name in ('tiny', 'base'):
    print('loading', name)
    WhisperModel(name, device='cpu', compute_type='int8')
print('whisper models ready')
\""
fi
