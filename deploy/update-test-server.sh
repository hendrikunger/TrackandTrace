#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/slf-trace/src/TrackandTrace}"
ENV_DIR="${ENV_DIR:-/opt/slf-trace/env}"
SERVER_ENV="${SERVER_ENV:-/etc/slf-trace/server.env}"
SERVICE_USER="${SERVICE_USER:-slf-trace}"
BRANCH="${BRANCH:-main}"
REMOTE="${REMOTE:-origin}"
LOG_DIR="${LOG_DIR:-/opt/slf-trace/logs}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_FILE="$LOG_DIR/update-server-$STAMP.log"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root, e.g. sudo $0" >&2
  exit 1
fi

mkdir -p "$LOG_DIR"
touch "$LOG_FILE"
chown "$SERVICE_USER:$SERVICE_USER" "$LOG_FILE"

exec > >(tee -a "$LOG_FILE") 2>&1

echo "Starting SLF Track and Trace test-server update at $STAMP"
echo "App directory: $APP_DIR"
echo "Branch: $REMOTE/$BRANCH"
echo "Scope: API VM only. This script must not run on a station/panel host."

if systemctl list-unit-files slf-trace-companion.service >/dev/null 2>&1; then
  echo "Refusing to run: slf-trace-companion.service is installed on this host." >&2
  echo "Use deploy/update-test-station.sh only for station-side companion changes." >&2
  exit 1
fi

if [[ ! -d "$APP_DIR/.git" ]]; then
  echo "Expected a git checkout at $APP_DIR." >&2
  exit 1
fi

if [[ ! -f "$SERVER_ENV" ]]; then
  echo "Missing server environment file: $SERVER_ENV" >&2
  exit 1
fi

if [[ ! -x "$ENV_DIR/bin/python" ]]; then
  echo "Missing Python environment: $ENV_DIR" >&2
  exit 1
fi

run_as_service_user() {
  sudo -u "$SERVICE_USER" \
    --preserve-env=PATH,APP_ENV,APP_HOST,APP_PORT,UI_HOST,UI_PORT,UI_AUTORELOAD,DATABASE_HOST,DATABASE_PORT,DATABASE_NAME,DATABASE_USER,DATABASE_PASSWORD,SERVER_URL,COMPANION_AUTH_REQUIRED \
    "$@"
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

echo "Installing package into existing environment..."
run_as_service_user "$ENV_DIR/bin/python" -m pip install -e .

echo "Running database migrations..."
set -a
# shellcheck disable=SC1090
source "$SERVER_ENV"
set +a
run_as_service_user "$ENV_DIR/bin/alembic" -c alembic.ini upgrade head

echo "Restarting API VM services only: slf-trace-api.service and slf-trace-ui.service."
echo "This does not contact or restart any station companion service."
systemctl restart slf-trace-api.service
if systemctl list-unit-files slf-trace-ui.service >/dev/null 2>&1; then
  systemctl restart slf-trace-ui.service
fi

echo "Checking services..."
systemctl is-active slf-trace-api.service
if systemctl list-unit-files slf-trace-ui.service >/dev/null 2>&1; then
  systemctl is-active slf-trace-ui.service
fi

health_url="http://127.0.0.1:${APP_PORT:-8000}/health?database=false"
echo "Checking $health_url"
for attempt in $(seq 1 30); do
  if curl -fsS "$health_url"; then
    echo
    break
  fi

  if [[ "$attempt" -eq 30 ]]; then
    echo "Health check failed after $attempt attempts." >&2
    exit 1
  fi

  sleep 1
done

echo "Update complete. Log: $LOG_FILE"
