#!/usr/bin/env bash
# Generate a self-signed TLS certificate for the Govee Charts web UI.
# Includes localhost + detected LAN IPs so https://192.168.x.x works for
# browser geolocation (secure context).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SSL_DIR="${ROOT}/data/ssl"
CERT="${SSL_DIR}/cert.pem"
KEY="${SSL_DIR}/key.pem"
DAYS="${SSL_DAYS:-825}"
FORCE=0
EXTRA_SANS=()

usage() {
  cat <<EOF
Usage: $0 [--force] [--san NAME_OR_IP]...

  Writes ${CERT} and ${KEY} (RSA 2048, ${DAYS} days).
  SANs always include localhost, 127.0.0.1, ::1, hostname, and LAN IPv4s.

  --force     Overwrite existing files
  --san X     Extra DNS name or IP (repeatable)
  SSL_DAYS    Override validity (default ${DAYS})
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --force|-f)
      FORCE=1
      shift
      ;;
    --san)
      EXTRA_SANS+=("$2")
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ -f "$CERT" && -f "$KEY" && "$FORCE" -ne 1 ]]; then
  echo "SSL cert already exists: ${CERT}"
  echo "Use --force to regenerate."
  exit 0
fi

if ! command -v openssl >/dev/null 2>&1; then
  echo "openssl is required" >&2
  exit 1
fi

mkdir -p "$SSL_DIR"
chmod 700 "$SSL_DIR"

HOST_NAME="$(hostname -s 2>/dev/null || hostname || echo govee-charts)"
FQDN="$(hostname -f 2>/dev/null || true)"

SAN_DNS=("localhost" "${HOST_NAME}" "govee-charts.local")
SAN_IP=("127.0.0.1" "::1")

if [[ -n "$FQDN" && "$FQDN" != "$HOST_NAME" && "$FQDN" != *localhost* ]]; then
  SAN_DNS+=("$FQDN")
fi

# IPv4 LAN addresses
if command -v hostname >/dev/null 2>&1; then
  for ip in $(hostname -I 2>/dev/null || true); do
    if [[ "$ip" == *:* ]]; then
      continue  # skip IPv6 here; ::1 already added; add explicit below
    fi
    SAN_IP+=("$ip")
  done
fi

# Optional: first global IPv6 (excluding link-local)
if command -v ip >/dev/null 2>&1; then
  while read -r ip6; do
    [[ -z "$ip6" ]] && continue
    SAN_IP+=("$ip6")
  done < <(ip -6 -o addr show scope global 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | head -n 3)
fi

for extra in "${EXTRA_SANS[@]+"${EXTRA_SANS[@]}"}"; do
  if [[ "$extra" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ || "$extra" == *:* ]]; then
    SAN_IP+=("$extra")
  else
    SAN_DNS+=("$extra")
  fi
done

# Deduplicate
dedupe() {
  local -a out=()
  local x
  for x in "$@"; do
    [[ -z "$x" ]] && continue
    local seen=0
    local y
    for y in "${out[@]+"${out[@]}"}"; do
      if [[ "$x" == "$y" ]]; then seen=1; break; fi
    done
    if [[ "$seen" -eq 0 ]]; then out+=("$x"); fi
  done
  printf '%s\n' "${out[@]+"${out[@]}"}"
}

mapfile -t SAN_DNS < <(dedupe "${SAN_DNS[@]}")
mapfile -t SAN_IP < <(dedupe "${SAN_IP[@]}")

SAN_LINE=""
for d in "${SAN_DNS[@]}"; do
  SAN_LINE="${SAN_LINE}DNS:${d},"
done
for ip in "${SAN_IP[@]}"; do
  SAN_LINE="${SAN_LINE}IP:${ip},"
done
SAN_LINE="${SAN_LINE%,}"

CONF="$(mktemp)"
trap 'rm -f "$CONF"' EXIT

cat >"$CONF" <<EOF
[req]
default_bits = 2048
prompt = no
default_md = sha256
distinguished_name = dn
x509_extensions = v3_req

[dn]
CN = govee-charts
O = Govee Charts
OU = Local LAN

[v3_req]
basicConstraints = CA:FALSE
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = ${SAN_LINE}
EOF

openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout "$KEY" \
  -out "$CERT" \
  -days "$DAYS" \
  -config "$CONF" \
  >/dev/null

chmod 600 "$KEY"
chmod 644 "$CERT"

echo "Created ${CERT}"
echo "         ${KEY}"
echo "SANs: ${SAN_LINE}"
echo
echo "Enable in config.toml:"
echo "  [server]"
echo "  ssl = true"
echo "  ssl_port = 8081"
echo
echo "Then open https://<lan-ip>:8081 and accept the browser warning once."
echo "HTTP remains on port 8080 for compatibility."
