#!/usr/bin/env bash
# Exit non-zero if production hygiene checks fail.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

fail=0
note() { printf '%s\n' "$*"; }
warn() { note "WARN: $*"; }
die() { note "FAIL: $*"; fail=1; }

# --- wabot-agent send policy ---
if [[ -f data/runtime_overrides.json ]]; then
  if grep -q '"send_policy"[[:space:]]*:[[:space:]]*"allow_all"' data/runtime_overrides.json 2>/dev/null; then
    die 'data/runtime_overrides.json has send_policy=allow_all (run scripts/apply-production-hygiene.py)'
  fi
fi

if [[ -f .env ]] && grep -q '^WABOT_AGENT_SEND_POLICY=allow_all' .env 2>/dev/null; then
  die '.env has WABOT_AGENT_SEND_POLICY=allow_all'
fi

# --- inbound webhook auth (wabot → agent on loopback) ---
if [[ -f .env ]]; then
  inbound_tok="$(grep -E '^WABOT_INBOUND_TOKEN=' .env | cut -d= -f2- || true)"
  if [[ -z "$inbound_tok" ]]; then
    die 'WABOT_INBOUND_TOKEN must be set in .env (inbound webhooks fail closed without it)'
  fi
fi

# --- operator auth before public tunnel ---
if [[ -f .env ]]; then
  cf_req="$(grep -E '^WABOT_AGENT_CF_ACCESS_REQUIRED=' .env | cut -d= -f2- | tr '[:upper:]' '[:lower:]' || true)"
  op_tok="$(grep -E '^WABOT_AGENT_OPERATOR_TOKEN=' .env | cut -d= -f2- || true)"
  if [[ "$cf_req" != "true" && -z "$op_tok" ]]; then
    warn 'no operator token and CF Access off — dashboard is open on loopback only'
  fi
  if [[ "$cf_req" == "true" ]]; then
    for v in WABOT_AGENT_CF_ACCESS_TEAM_DOMAIN WABOT_AGENT_CF_ACCESS_AUD; do
      if ! grep -q "^${v}=" .env || [[ -z "$(grep "^${v}=" .env | cut -d= -f2-)" ]]; then
        die "CF Access required but $v is unset"
      fi
    done
  fi
fi

# --- wabot loopback ---
if [[ -z "${WABOT_ENV:-}" ]]; then
  if [[ -f "$ROOT/../wabot/wabot.env" ]]; then
    WABOT_ENV="$ROOT/../wabot/wabot.env"
  else
    WABOT_ENV="$ROOT/../../wabot/wabot.env"
  fi
fi
if [[ -f "$WABOT_ENV" ]]; then
  addr="$(grep -E '^WABOT_HTTP_ADDR=' "$WABOT_ENV" | cut -d= -f2- || echo '127.0.0.1:7777')"
  host="${addr%%:*}"
  if [[ "$host" != "127.0.0.1" && "$host" != "localhost" ]]; then
    die "wabot HTTP must be loopback-only (WABOT_HTTP_ADDR=$addr)"
  fi
  for key in WABOT_INBOUND_URL WABOT_RECEIPT_URL WABOT_PRESENCE_URL WABOT_HISTORY_URL WABOT_HISTORY_SYNC_URL; do
    url="$(grep -E "^${key}=" "$WABOT_ENV" | cut -d= -f2- || true)"
    if [[ -n "$url" && "$url" != *127.0.0.1* && "$url" != *localhost* ]]; then
      die "$key must target loopback ($url)"
    fi
  done
else
  warn "wabot.env not found at $WABOT_ENV"
fi

# --- cloudflared must not expose wabot daemon port ---
CF_CFG="${CLOUDFLARED_CONFIG:-/etc/cloudflared/config.yml}"
if [[ -f "$CF_CFG" ]]; then
  if grep -q ':7777' "$CF_CFG" 2>/dev/null; then
    die "cloudflared config must not route port 7777 (wabot daemon)"
  fi
  if ! grep -q '127.0.0.1:8787' "$CF_CFG" 2>/dev/null; then
    warn 'cloudflared config should origin to http://127.0.0.1:8787'
  fi
fi

# --- secret file modes (best effort) ---
for f in .env data/runtime_overrides.json "$WABOT_ENV"; do
  [[ -f "$f" ]] || continue
  mode="$(stat -c '%a' "$f" 2>/dev/null || stat -f '%Lp' "$f" 2>/dev/null || echo '')"
  if [[ -n "$mode" && "$mode" != "600" ]]; then
    warn "$f permissions are $mode (expected 600) — run: chmod 600 $f"
  fi
done

if [[ "$fail" -ne 0 ]]; then
  exit 1
fi
note 'ok: production hygiene checks passed'
