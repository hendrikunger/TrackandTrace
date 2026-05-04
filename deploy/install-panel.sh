#!/usr/bin/env bash
set -euo pipefail

INSTALL_ROOT="${INSTALL_ROOT:-/opt/slf-trace}"
RELEASE_SOURCE="${1:-.}"
SERVICE_USER="${SERVICE_USER:-slf-trace}"

RELEASE_SOURCE="$(cd "$RELEASE_SOURCE" && pwd)"
VERSION="$(head -n 1 "$RELEASE_SOURCE/VERSION")"
RELEASE_DIR="$INSTALL_ROOT/releases/$VERSION"
CURRENT_DIR="$INSTALL_ROOT/current"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root, e.g. sudo $0 $RELEASE_SOURCE" >&2
  exit 1
fi

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --home "$INSTALL_ROOT" --shell /usr/sbin/nologin "$SERVICE_USER"
fi

mkdir -p "$RELEASE_DIR" "$INSTALL_ROOT/logs" "$INSTALL_ROOT/state" /etc/slf-trace

if [[ -f "$RELEASE_SOURCE/env.tar.gz" ]]; then
  mkdir -p "$RELEASE_DIR/env"
  tar -xzf "$RELEASE_SOURCE/env.tar.gz" -C "$RELEASE_DIR/env"
  if [[ -x "$RELEASE_DIR/env/bin/conda-unpack" ]]; then
    "$RELEASE_DIR/env/bin/conda-unpack"
  fi
elif [[ -d "$RELEASE_SOURCE/env" ]]; then
  cp -a "$RELEASE_SOURCE/env" "$RELEASE_DIR/env"
else
  echo "Release source must contain env.tar.gz or env directory." >&2
  exit 1
fi

cp "$RELEASE_SOURCE/alembic.ini" "$RELEASE_DIR/" 2>/dev/null || true
cp -a "$RELEASE_SOURCE/migrations" "$RELEASE_DIR/" 2>/dev/null || true
cp -a "$RELEASE_SOURCE/deploy" "$RELEASE_DIR/"

if [[ ! -f /etc/slf-trace/panel.env ]]; then
  cp "$RELEASE_DIR/deploy/templates/panel.env.example" /etc/slf-trace/panel.env
  echo "Created /etc/slf-trace/panel.env. Edit SERVER_URL, DATABASE_*, and STATION_ID."
fi

ln -sfn "$RELEASE_DIR" "$CURRENT_DIR"
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_ROOT" /etc/slf-trace

cp "$RELEASE_DIR/deploy/systemd/slf-trace-ui.service" /etc/systemd/system/
cp "$RELEASE_DIR/deploy/systemd/slf-trace-companion.service" /etc/systemd/system/

systemctl daemon-reload
systemctl enable slf-trace-ui.service slf-trace-companion.service

echo "Installed SLF Track and Trace panel release $VERSION at $CURRENT_DIR"
echo "Edit /etc/slf-trace/panel.env if needed, then run:"
echo "  systemctl restart slf-trace-ui.service slf-trace-companion.service"
