#!/usr/bin/env bash
# Build the React SPA in web/ and mirror the output into static/.
# FastAPI serves static/ at /static/*; index.html is also served at /.
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -d web ]]; then
  echo "web/ not found" >&2
  exit 1
fi

pushd web >/dev/null
if [[ ! -d node_modules ]] || [[ package-lock.json -nt node_modules ]]; then
  npm ci
fi
npm run build
popd >/dev/null

# Preserve favicon.svg; mirror everything else from web/dist/.
mkdir -p static
find static -mindepth 1 ! -name favicon.svg -delete
cp -R web/dist/. static/
echo "static/ updated from web/dist/"
