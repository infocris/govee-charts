#!/usr/bin/env bash
# Install or remove the govee-charts systemd unit (system scope).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_NAME="govee-charts"
TEMPLATE="${ROOT}/deploy/govee-charts.service.in"
UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}.service"
EXTRA_ARGS=""

usage() {
  cat <<EOF
Usage: $0 [--hub] install|uninstall|restart|status

  install     Write ${UNIT_PATH}, enable and start the service (needs sudo)
  uninstall   Stop, disable and remove the unit (needs sudo)
  restart     Restart the service (needs sudo)
  status      Show service status

  --hub       Web UI only (pass --no-scanner to the app)
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --hub|--no-scanner)
      EXTRA_ARGS=" --no-scanner"
      shift
      ;;
    install|uninstall|restart|status)
      ACTION="$1"
      shift
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

: "${ACTION:?Action required: install, uninstall, restart, or status}"

if [[ ! -x "${ROOT}/venv/bin/python" ]]; then
  echo "Missing venv — run: make install" >&2
  exit 1
fi

if [[ ! -f "${ROOT}/config.toml" ]]; then
  echo "Missing config.toml — run: make install" >&2
  exit 1
fi

case "$ACTION" in
  install)
    RUN_USER="${SUDO_USER:-$USER}"
    if [[ "$RUN_USER" == "root" ]]; then
      echo "Run with sudo from your login user, e.g. sudo ./scripts/install-systemd.sh install" >&2
      exit 1
    fi
    RUN_GROUP="$(id -gn "$RUN_USER")"
    sed \
      -e "s|@ROOT@|${ROOT}|g" \
      -e "s|@USER@|${RUN_USER}|g" \
      -e "s|@GROUP@|${RUN_GROUP}|g" \
      -e "s|@EXTRA_ARGS@|${EXTRA_ARGS}|g" \
      "$TEMPLATE" | sudo tee "$UNIT_PATH" >/dev/null
    sudo systemctl daemon-reload
    sudo systemctl enable --now "$SERVICE_NAME"
    echo "Installed ${SERVICE_NAME} (user=${RUN_USER}, root=${ROOT})"
    echo "Logs: journalctl -u ${SERVICE_NAME} -f"
    echo "      tail -f ${ROOT}/govee-charts.log"
    ;;
  uninstall)
    sudo systemctl disable --now "$SERVICE_NAME" 2>/dev/null || true
    sudo rm -f "$UNIT_PATH"
    sudo systemctl daemon-reload
    echo "Removed ${SERVICE_NAME}"
    ;;
  restart)
    sudo systemctl restart "$SERVICE_NAME"
    echo "Restarted ${SERVICE_NAME}"
    ;;
  status)
    systemctl status "$SERVICE_NAME" --no-pager || true
    ;;
esac
