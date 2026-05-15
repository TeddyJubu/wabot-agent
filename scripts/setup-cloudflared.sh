#!/usr/bin/env bash
# Idempotent installer for cloudflared on the wabot-agent VPS.
#
# Steps:
#   1. Install cloudflared from the official Cloudflare apt repo (skip if present).
#   2. Run `cloudflared tunnel login` (browser-based, copies cert.pem to /etc/cloudflared).
#   3. Create the tunnel "wabot-agent" (skip if it already exists).
#   4. Write /etc/cloudflared/config.yml from the template, substituting the
#      tunnel UUID and the user-supplied hostname.
#   5. Route the chosen hostname's DNS to the tunnel.
#   6. Install + enable the systemd unit.
#   7. Print next steps for Cloudflare Access (done in the dashboard).
#
# Usage:
#   sudo ./scripts/setup-cloudflared.sh wabot.example.com
#
# Re-running with the same hostname is safe: no duplicate tunnels, no
# duplicate DNS records, no service flapping.

set -euo pipefail

if [[ ${EUID:-1000} -ne 0 ]]; then
  echo "This script must be run as root (sudo)." >&2
  exit 1
fi

HOSTNAME_ARG="${1:-}"
if [[ -z "${HOSTNAME_ARG}" ]]; then
  echo "Usage: sudo $0 <hostname e.g. wabot.example.com>" >&2
  exit 2
fi

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TUNNEL_NAME="wabot-agent"
CONFIG_DIR="/etc/cloudflared"
SYSTEMD_UNIT="/etc/systemd/system/cloudflared.service"

echo "==> Installing cloudflared (if missing)"
if ! command -v cloudflared >/dev/null 2>&1; then
  mkdir -p --mode=0755 /usr/share/keyrings
  curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg \
    | tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
  echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared $(lsb_release -cs) main" \
    | tee /etc/apt/sources.list.d/cloudflared.list
  apt-get update
  apt-get install -y cloudflared
else
  echo "cloudflared already present: $(cloudflared --version | head -1)"
fi

echo "==> Ensuring config dir exists"
mkdir -p "${CONFIG_DIR}"

echo "==> Logging in to Cloudflare (browser flow, only if cert is missing)"
if [[ ! -f "${CONFIG_DIR}/cert.pem" ]]; then
  cloudflared tunnel login
  # cert.pem lands in $HOME/.cloudflared/ on success — move it to /etc/cloudflared
  # so the service user can read it.
  if [[ -f "${HOME}/.cloudflared/cert.pem" ]]; then
    install -m 0640 "${HOME}/.cloudflared/cert.pem" "${CONFIG_DIR}/cert.pem"
  fi
fi

echo "==> Creating tunnel '${TUNNEL_NAME}' (if missing)"
if ! cloudflared --origincert "${CONFIG_DIR}/cert.pem" tunnel list 2>/dev/null \
  | grep -q " ${TUNNEL_NAME} "; then
  cloudflared --origincert "${CONFIG_DIR}/cert.pem" tunnel create "${TUNNEL_NAME}"
fi

TUNNEL_UUID="$(cloudflared --origincert "${CONFIG_DIR}/cert.pem" tunnel list \
  | awk -v n="${TUNNEL_NAME}" '$2==n {print $1; exit}')"
if [[ -z "${TUNNEL_UUID}" ]]; then
  echo "Could not resolve tunnel UUID for '${TUNNEL_NAME}'" >&2
  exit 3
fi
echo "Tunnel UUID: ${TUNNEL_UUID}"

# Move the credentials JSON into the config dir if it isn't there yet.
CRED_SRC="${HOME}/.cloudflared/${TUNNEL_UUID}.json"
CRED_DST="${CONFIG_DIR}/${TUNNEL_UUID}.json"
if [[ -f "${CRED_SRC}" && ! -f "${CRED_DST}" ]]; then
  install -m 0640 "${CRED_SRC}" "${CRED_DST}"
fi

echo "==> Writing ${CONFIG_DIR}/config.yml"
sed \
  -e "s|REPLACE_WITH_TUNNEL_UUID|${TUNNEL_UUID}|g" \
  -e "s|wabot.REPLACE_WITH_YOUR_DOMAIN|${HOSTNAME_ARG}|g" \
  "${REPO_DIR}/deploy/cloudflared/config.yml.example" \
  > "${CONFIG_DIR}/config.yml"
chmod 0644 "${CONFIG_DIR}/config.yml"

echo "==> Routing DNS ${HOSTNAME_ARG} -> tunnel ${TUNNEL_UUID}"
cloudflared --origincert "${CONFIG_DIR}/cert.pem" tunnel route dns \
  "${TUNNEL_NAME}" "${HOSTNAME_ARG}" || true

echo "==> Creating cloudflared system user (if missing)"
if ! id cloudflared >/dev/null 2>&1; then
  useradd --system --no-create-home --shell /usr/sbin/nologin cloudflared
fi
chown -R cloudflared:cloudflared "${CONFIG_DIR}"

echo "==> Installing systemd unit"
install -m 0644 "${REPO_DIR}/deploy/systemd/cloudflared.service" "${SYSTEMD_UNIT}"
systemctl daemon-reload
systemctl enable --now cloudflared.service

cat <<EOF

✓ cloudflared is running for ${HOSTNAME_ARG}.

Next steps (manual, in the Cloudflare dashboard):
  1. Zero Trust > Access > Applications > Add an application
     - Type: Self-hosted
     - Application domain: ${HOSTNAME_ARG}
     - Note the Application Audience tag — you'll set
       WABOT_AGENT_CF_ACCESS_AUD to this value.
  2. Add a Policy: "Google login" or "One-time PIN", restricted to your
     email (or a small allowlist).
  3. In .env on the VPS, set:
       WABOT_AGENT_CF_ACCESS_TEAM_DOMAIN=<yourteam>.cloudflareaccess.com
       WABOT_AGENT_CF_ACCESS_AUD=<aud from step 1>
       WABOT_AGENT_CF_ACCESS_REQUIRED=true
  4. systemctl restart wabot-agent.service

Test from a phone:  https://${HOSTNAME_ARG}/pair
EOF
