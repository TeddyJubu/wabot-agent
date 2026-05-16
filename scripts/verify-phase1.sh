#!/usr/bin/env bash
# Phase 1 verification: CI-parity checks + optional live smoke against wabot + wabot-agent.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

WABOT_ENDPOINT="${WABOT_ENDPOINT:-http://127.0.0.1:7777}"
AGENT_ENDPOINT="${WABOT_AGENT_ENDPOINT:-http://127.0.0.1:8787}"
SKIP_LIVE="${SKIP_LIVE:-0}"

pass() { printf '  ✓ %s\n' "$1"; }
fail() { printf '  ✗ %s\n' "$1"; exit 1; }
section() { printf '\n==> %s\n' "$1"; }

ENV_BACKUP=""
cleanup() {
  if [[ -n "$ENV_BACKUP" && -f "$ENV_BACKUP" ]]; then
    mv -f "$ENV_BACKUP" "$ROOT/.env"
  fi
}
trap cleanup EXIT

section "Backend (ruff + pytest offline, isolated from .env)"
if [[ -f "$ROOT/.env" ]]; then
  ENV_BACKUP="$ROOT/.env.verify-phase1.bak"
  mv -f "$ROOT/.env" "$ENV_BACKUP"
fi
# Clear env vars that leak from a sourced .env into the shell and break offline tests.
unset WABOT_AGENT_CF_ACCESS_TEAM_DOMAIN WABOT_AGENT_CF_ACCESS_AUD WABOT_AGENT_CF_ACCESS_REQUIRED
unset VIGNESH_CF_ACCESS_TEAM_DOMAIN VIGNESH_CF_ACCESS_AUD VIGNESH_CF_ACCESS_REQUIRED
unset OPENROUTER_API_KEY OPENROUTER_MODEL OPENROUTER_BASE_URL
uv run ruff check .
uv run pytest -q -m "not live"
pass "ruff + pytest"

section "Eval harness (offline)"
uv run python evals/run_local.py
pass "evals"

section "Web (vitest + build)"
(
  cd web
  npm ci --silent
  npm run test -- --run
  npm run build
)
pass "vitest + build"

section "wabot Go tests"
WABOT_HOME="${WABOT_HOME:-$HOME/Desktop/Code-hub/wabot}"
if [[ -d "$WABOT_HOME" ]]; then
  (cd "$WABOT_HOME" && go test ./cmd/wabot/... -count=1)
  pass "wabot go test"
else
  printf '  ⚠ skip wabot go test (WABOT_HOME not found: %s)\n' "$WABOT_HOME"
fi

if [[ "$SKIP_LIVE" == "1" ]]; then
  section "Live smoke skipped (SKIP_LIVE=1)"
  exit 0
fi

section "Live smoke (wabot + wabot-agent daemons)"
if ! curl -sf "$WABOT_ENDPOINT/health" >/dev/null 2>&1; then
  fail "wabot not reachable at $WABOT_ENDPOINT (start wabot or set SKIP_LIVE=1)"
fi
if ! curl -sf "$AGENT_ENDPOINT/health" >/dev/null 2>&1; then
  fail "wabot-agent not reachable at $AGENT_ENDPOINT"
fi

TOKEN="${WABOT_TOKEN:-}"
if [[ -z "$TOKEN" && -f "${WABOT_TOKEN_FILE:-$HOME/.config/wabot/token}" ]]; then
  TOKEN="$(tr -d '[:space:]' < "${WABOT_TOKEN_FILE:-$HOME/.config/wabot/token}")"
fi
if [[ -z "$TOKEN" ]]; then
  fail "WABOT_TOKEN or token file required for live smoke"
fi

auth=(-H "X-Token: $TOKEN")

health="$(curl -sf "$WABOT_ENDPOINT/health")"
echo "$health" | grep -q '"connected"' || fail "wabot /health unexpected: $health"
pass "wabot /health"

ready="$(curl -sf "$AGENT_ENDPOINT/ready")"
echo "$ready" | grep -q '"ok"' || fail "agent /ready unexpected: $ready"
pass "agent /ready"

pairing="$(curl -sf "${auth[@]}" "$WABOT_ENDPOINT/pairing/qr")"
echo "$pairing" | grep -qE '"logged_in"|"qr"' || fail "wabot /pairing/qr unexpected: $pairing"
pass "wabot /pairing/qr"

inbox="$(curl -sf "${auth[@]}" "$WABOT_ENDPOINT/inbox/recent?limit=5")"
echo "$inbox" | grep -q '"messages"' || fail "wabot /inbox/recent unexpected: $inbox"
pass "wabot /inbox/recent"

lookup="$(curl -sf "${auth[@]}" -H "Content-Type: application/json" \
  -d '{"phones":["+15555550100"]}' "$WABOT_ENDPOINT/contacts/lookup")"
echo "$lookup" | grep -q '"results"' || fail "contacts/lookup unexpected: $lookup"
pass "wabot /contacts/lookup"

groups="$(curl -sf "${auth[@]}" "$WABOT_ENDPOINT/groups")"
echo "$groups" | grep -qE '"groups"|"count"' || fail "wabot /groups unexpected: $groups"
pass "wabot /groups"

# Read/typing need a chat JID + message id from observed inbound traffic.
read_inbox_meta() {
  echo "$inbox" | python3 -c "
import json, sys
data = json.load(sys.stdin)
msgs = data.get('messages') or []
if not msgs:
    sys.exit(1)
last = msgs[-1]
print(last.get('chat', ''), last.get('id', ''), sep='\t')
"
}

if meta="$(read_inbox_meta 2>/dev/null)"; then
  chat_jid="${meta%%$'\t'*}"
  msg_id="${meta#*$'\t'}"
  read_code="$(curl -sf -o /dev/null -w '%{http_code}' "${auth[@]}" \
    -H "Content-Type: application/json" \
    -d "{\"chat\":\"$chat_jid\",\"message_ids\":[\"$msg_id\"]}" \
    "$WABOT_ENDPOINT/chats/read")"
  [[ "$read_code" == "200" ]] || fail "wabot /chats/read returned $read_code"
  pass "wabot /chats/read"

  type_code="$(curl -sf -o /dev/null -w '%{http_code}' "${auth[@]}" \
    -H "Content-Type: application/json" \
    -d "{\"to\":\"$chat_jid\",\"state\":\"composing\"}" \
    "$WABOT_ENDPOINT/presence/typing")"
  [[ "$type_code" == "200" ]] || fail "wabot /presence/typing returned $type_code"
  pass "wabot /presence/typing"
else
  printf '  ⚠ skip /chats/read and /presence/typing (no inbound messages yet)\n'
fi

agent_pairing="$(curl -sf "$AGENT_ENDPOINT/api/whatsapp/pairing")"
echo "$agent_pairing" | grep -q '"supported"' || fail "agent pairing unexpected: $agent_pairing"
pass "agent GET /api/whatsapp/pairing"

printf '\nAll Phase 1 checks passed.\n'
