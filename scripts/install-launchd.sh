#!/usr/bin/env bash
# Install or remove the govee-charts LaunchAgent (macOS, user scope).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="com.govee-charts"
TEMPLATE="${ROOT}/deploy/govee-charts.plist.in"
PLIST_PATH="${HOME}/Library/LaunchAgents/${LABEL}.plist"
DOMAIN="gui/$(id -u)"
EXTRA_ARGS_XML=""

usage() {
  cat <<EOF
Usage: $0 [--hub] install|uninstall|restart|status

  install     Write ${PLIST_PATH}, load and start the agent
  uninstall   Unload and remove the LaunchAgent
  restart     Restart the agent
  status      Show agent status

  --hub       Web UI only (pass --no-scanner to the app)

Runs as your login user (no sudo). Starts at login via LaunchAgents.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --hub|--no-scanner)
      EXTRA_ARGS_XML=$'\t\t<string>--no-scanner</string>'
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

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This script is for macOS only (launchd). On Linux use scripts/install-systemd.sh" >&2
  exit 1
fi

if [[ ! -x "${ROOT}/venv/bin/python" ]]; then
  echo "Missing venv — run: make install" >&2
  exit 1
fi

if [[ ! -f "${ROOT}/config.toml" ]]; then
  echo "Missing config.toml — run: make install" >&2
  exit 1
fi

is_loaded() {
  launchctl print "${DOMAIN}/${LABEL}" &>/dev/null
}

bootout_if_loaded() {
  if is_loaded; then
    launchctl bootout "${DOMAIN}/${LABEL}" 2>/dev/null || true
  fi
}

case "$ACTION" in
  install)
    mkdir -p "$(dirname "$PLIST_PATH")"
    # shellcheck disable=SC2016
    sed \
      -e "s|@ROOT@|${ROOT}|g" \
      -e "s|@EXTRA_ARGS_XML@|${EXTRA_ARGS_XML}|g" \
      "$TEMPLATE" >"$PLIST_PATH"
    bootout_if_loaded
    launchctl bootstrap "$DOMAIN" "$PLIST_PATH"
    echo "Installed ${LABEL} (user=$(id -un), root=${ROOT})"
    echo "Logs: tail -f ${ROOT}/govee-charts.log"
    echo "      tail -f ${ROOT}/govee-charts.launchd.log"
    echo "Note: allow Bluetooth for this process under"
    echo "      System Settings → Privacy & Security → Bluetooth"
    ;;
  uninstall)
    bootout_if_loaded
    rm -f "$PLIST_PATH"
    echo "Removed ${LABEL}"
    ;;
  restart)
    if [[ ! -f "$PLIST_PATH" ]]; then
      echo "LaunchAgent not installed — run: make launchd-install" >&2
      exit 1
    fi
    if is_loaded; then
      launchctl kickstart -k "${DOMAIN}/${LABEL}"
    else
      launchctl bootstrap "$DOMAIN" "$PLIST_PATH"
    fi
    echo "Restarted ${LABEL}"
    ;;
  status)
    if is_loaded; then
      launchctl print "${DOMAIN}/${LABEL}"
    else
      echo "${LABEL} is not loaded"
      if [[ -f "$PLIST_PATH" ]]; then
        echo "Plist exists at ${PLIST_PATH} but is not loaded"
      fi
      exit 1
    fi
    ;;
esac
