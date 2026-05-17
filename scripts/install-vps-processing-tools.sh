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
