#!/usr/bin/env bash
# Install/manage split govee-charts systemd units (system scope).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UI_SERVICE="govee-charts-ui"
WORKERS_SERVICE="govee-charts-workers"
UI_TEMPLATE="${ROOT}/deploy/govee-charts-ui.service.in"
WORKERS_TEMPLATE="${ROOT}/deploy/govee-charts-workers.service.in"
UI_UNIT_PATH="/etc/systemd/system/${UI_SERVICE}.service"
WORKERS_UNIT_PATH="/etc/systemd/system/${WORKERS_SERVICE}.service"

usage() {
  cat <<EOF
Usage: $0 [--target all|ui|workers] install|uninstall|restart-ui|restart-workers|restart-all|status

  install         Write unit(s), enable and start selected target(s) (needs sudo)
  uninstall       Stop, disable and remove selected target(s) (needs sudo)
  restart-ui      Restart ${UI_SERVICE} only (needs sudo)
  restart-workers Restart ${WORKERS_SERVICE} only (needs sudo)
  restart-all     Restart both services (needs sudo)
  status          Show status for both services

  --target        Service target for install/uninstall (default: all)
EOF
}

TARGET="all"
ACTION=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --target)
      TARGET="${2:-}"
      shift 2
      ;;
    install|uninstall|restart-ui|restart-workers|restart-all|status)
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

if [[ "$TARGET" != "all" && "$TARGET" != "ui" && "$TARGET" != "workers" ]]; then
  echo "Invalid --target value: ${TARGET}" >&2
  exit 1
fi

: "${ACTION:?Action required}"

if [[ ! -x "${ROOT}/venv/bin/python" ]]; then
  echo "Missing venv — run: make install" >&2
  exit 1
fi

if [[ ! -f "${ROOT}/config.toml" ]]; then
  echo "Missing config.toml — run: make install" >&2
  exit 1
fi

install_unit() {
  local template="$1"
  local unit_path="$2"
  local run_user="$3"
  local run_group="$4"
  sed \
    -e "s|@ROOT@|${ROOT}|g" \
    -e "s|@USER@|${run_user}|g" \
    -e "s|@GROUP@|${run_group}|g" \
    "$template" | sudo tee "$unit_path" >/dev/null
}

install_selected() {
  local run_user="$1"
  local run_group="$2"
  if [[ "$TARGET" == "all" || "$TARGET" == "ui" ]]; then
    install_unit "$UI_TEMPLATE" "$UI_UNIT_PATH" "$run_user" "$run_group"
  fi
  if [[ "$TARGET" == "all" || "$TARGET" == "workers" ]]; then
    install_unit "$WORKERS_TEMPLATE" "$WORKERS_UNIT_PATH" "$run_user" "$run_group"
  fi
}

enable_selected() {
  if [[ "$TARGET" == "all" || "$TARGET" == "ui" ]]; then
    sudo systemctl enable --now "$UI_SERVICE"
  fi
  if [[ "$TARGET" == "all" || "$TARGET" == "workers" ]]; then
    sudo systemctl enable --now "$WORKERS_SERVICE"
  fi
}

disable_selected() {
  if [[ "$TARGET" == "all" || "$TARGET" == "ui" ]]; then
    sudo systemctl disable --now "$UI_SERVICE" 2>/dev/null || true
    sudo rm -f "$UI_UNIT_PATH"
  fi
  if [[ "$TARGET" == "all" || "$TARGET" == "workers" ]]; then
    sudo systemctl disable --now "$WORKERS_SERVICE" 2>/dev/null || true
    sudo rm -f "$WORKERS_UNIT_PATH"
  fi
}

case "$ACTION" in
  install)
    RUN_USER="${SUDO_USER:-$USER}"
    if [[ "$RUN_USER" == "root" ]]; then
      echo "Run with sudo from your login user, e.g. sudo ./scripts/install-systemd.sh install" >&2
      exit 1
    fi
    RUN_GROUP="$(id -gn "$RUN_USER")"
    install_selected "$RUN_USER" "$RUN_GROUP"
    sudo systemctl daemon-reload
    enable_selected
    echo "Installed target=${TARGET} (user=${RUN_USER}, root=${ROOT})"
    echo "Logs: journalctl -u ${UI_SERVICE} -u ${WORKERS_SERVICE} -f"
    echo "      tail -f ${ROOT}/govee-charts.log"
    ;;
  uninstall)
    disable_selected
    sudo systemctl daemon-reload
    echo "Removed target=${TARGET}"
    ;;
  restart-ui)
    sudo systemctl restart "$UI_SERVICE"
    echo "Restarted ${UI_SERVICE}"
    ;;
  restart-workers)
    sudo systemctl restart "$WORKERS_SERVICE"
    echo "Restarted ${WORKERS_SERVICE}"
    ;;
  restart-all)
    sudo systemctl restart "$UI_SERVICE" "$WORKERS_SERVICE"
    echo "Restarted ${UI_SERVICE} and ${WORKERS_SERVICE}"
    ;;
  status)
    systemctl status "$UI_SERVICE" --no-pager || true
    systemctl status "$WORKERS_SERVICE" --no-pager || true
    ;;
esac
