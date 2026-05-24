#!/usr/bin/env bash
# Build the React SPA in web/ and mirror the output into static/.
# FastAPI serves static/ at /static/*; index.html is also served at /.
set -euo pipefail
cd "$(dirname "$0")/.."

# Unset NODE_ENV so `npm ci` always installs devDependencies — tsc needs
# @testing-library/jest-dom and vitest types per web/tsconfig.json. If the
# user's shell has NODE_ENV=production set (a common gotcha when nvm /
# pyenv / homebrew profile fragments leak it), npm ci silently skips
# devDeps and the next `npm run build` fails with "Cannot find type
# definition file" errors. Same root cause as the Phase 1 vitest fix.
unset NODE_ENV

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
