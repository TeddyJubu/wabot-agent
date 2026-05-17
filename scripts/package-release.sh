#!/usr/bin/env bash
# Build a distributable source tarball (no secrets, no .venv, no runtime data).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "package-release.sh must run inside a git checkout." >&2
  exit 1
fi

VERSION="$(
  python3 -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])"
)"
REF="${REF:-HEAD}"
DIST_DIR="${DIST_DIR:-$REPO_ROOT/dist}"
ARCHIVE_BASENAME="wabot-agent-${VERSION}"
ARCHIVE_PATH="${DIST_DIR}/${ARCHIVE_BASENAME}.tar.gz"
CHECKSUM_PATH="${ARCHIVE_PATH}.sha256"

mkdir -p "$DIST_DIR"

echo "Packaging wabot-agent ${VERSION} from ${REF} ..."
git archive --format=tar.gz \
  --prefix="${ARCHIVE_BASENAME}/" \
  "$REF" \
  -o "$ARCHIVE_PATH"

if command -v shasum >/dev/null 2>&1; then
  shasum -a 256 "$ARCHIVE_PATH" | tee "$CHECKSUM_PATH"
elif command -v sha256sum >/dev/null 2>&1; then
  sha256sum "$ARCHIVE_PATH" | tee "$CHECKSUM_PATH"
else
  echo "No shasum/sha256sum; skipped checksum file." >&2
fi

BYTES="$(wc -c <"$ARCHIVE_PATH" | tr -d ' ')"
echo ""
echo "Created: $ARCHIVE_PATH (${BYTES} bytes)"
echo "Verify:  shasum -a 256 -c ${CHECKSUM_PATH##*/}   # from dist/"
echo "Install: tar xzf ${ARCHIVE_BASENAME}.tar.gz && cd ${ARCHIVE_BASENAME} && ./scripts/install-from-release.sh"
