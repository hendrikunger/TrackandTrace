#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/slf-trace/src/TrackandTrace}"
ENV_DIR="${ENV_DIR:-/opt/slf-trace/current/env}"
PANEL_ENV="${PANEL_ENV:-/etc/slf-trace/panel.env}"
SERVICE_USER="${SERVICE_USER:-slf-trace}"
BRANCH="${BRANCH:-main}"
REMOTE="${REMOTE:-origin}"
LOG_DIR="${LOG_DIR:-/opt/slf-trace/logs}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_FILE="$LOG_DIR/update-station-$STAMP.log"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root, e.g. sudo $0" >&2
  exit 1
fi

mkdir -p "$LOG_DIR"
touch "$LOG_FILE"
chown "$SERVICE_USER:$SERVICE_USER" "$LOG_FILE"

exec > >(tee -a "$LOG_FILE") 2>&1

echo "Starting SLF Track and Trace test-station update at $STAMP"
echo "App directory: $APP_DIR"
echo "Branch: $REMOTE/$BRANCH"

if [[ ! -d "$APP_DIR/.git" ]]; then
  echo "Expected a git checkout at $APP_DIR." >&2
  exit 1
fi

if [[ ! -f "$PANEL_ENV" ]]; then
  echo "Missing station environment file: $PANEL_ENV" >&2
  exit 1
fi

if [[ ! -x "$ENV_DIR/bin/python" ]]; then
  echo "Missing Python environment: $ENV_DIR" >&2
  exit 1
fi

run_as_service_user() {
  sudo -u "$SERVICE_USER" --preserve-env=PATH "$@"
}

cd "$APP_DIR"

echo "Fetching latest source..."
run_as_service_user git fetch "$REMOTE" "$BRANCH"

current_head="$(run_as_service_user git rev-parse --short HEAD)"
target_head="$(run_as_service_user git rev-parse --short "$REMOTE/$BRANCH")"
echo "Current HEAD: $current_head"
echo "Target HEAD:  $target_head"

if [[ -n "$(run_as_service_user git status --porcelain)" ]]; then
  echo "Working tree has local changes. Refusing to overwrite them." >&2
  run_as_service_user git status --short
  exit 1
fi

run_as_service_user git checkout "$BRANCH"
run_as_service_user git pull --ff-only "$REMOTE" "$BRANCH"

echo "Installing package into existing station environment..."
run_as_service_user "$ENV_DIR/bin/python" -m pip install -e ".[smb,serial]"

echo "Refreshing kiosk launcher from checkout..."
if [[ -f deploy/linux/slf-trace-kiosk-browser ]]; then
  install -o root -g root -m 0755 deploy/linux/slf-trace-kiosk-browser \
    /usr/local/bin/slf-trace-kiosk-browser
fi

echo "Restarting station companion..."
systemctl restart slf-trace-companion.service

echo "Checking station companion..."
systemctl is-active slf-trace-companion.service

server_url="$(sed -n 's/^SERVER_URL=//p' "$PANEL_ENV" | tail -n 1)"
station_id="$(sed -n 's/^STATION_ID=//p' "$PANEL_ENV" | tail -n 1)"
if [[ -n "$server_url" && -n "$station_id" ]]; then
  kiosk_base_url="$(python3 - "$server_url" <<'PY'
from urllib.parse import urlsplit, urlunsplit
import sys

url = sys.argv[1]
parts = urlsplit(url)
if not parts.scheme or not parts.hostname:
    raise SystemExit(0)
host = parts.hostname
if ":" in host and not host.startswith("["):
    host = f"[{host}]"
print(urlunsplit((parts.scheme, f"{host}:5006", "", "", "")))
PY
)"
  if [[ -n "$kiosk_base_url" ]]; then
    kiosk_url="$kiosk_base_url/kiosk?station_id=$station_id"
    echo "Checking $kiosk_url"
    curl -fsS "$kiosk_url" >/dev/null
  fi
fi

echo "Update complete. Log: $LOG_FILE"
