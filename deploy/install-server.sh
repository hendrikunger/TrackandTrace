#!/usr/bin/env bash
set -euo pipefail

INSTALL_ROOT="${INSTALL_ROOT:-/opt/slf-trace}"
RELEASE_SOURCE="${1:-.}"
SERVICE_USER="${SERVICE_USER:-slf-trace}"
FORCE_REINSTALL="${FORCE_REINSTALL:-false}"

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

if [[ -e "$RELEASE_DIR" && "$FORCE_REINSTALL" == "true" ]]; then
  rm -rf "$RELEASE_DIR"
fi

mkdir -p "$RELEASE_DIR" "$INSTALL_ROOT/logs" "$INSTALL_ROOT/state" /etc/slf-trace

if [[ -f "$RELEASE_SOURCE/env.tar.gz" ]]; then
  mkdir -p "$RELEASE_DIR/env"
  tar -xzf "$RELEASE_SOURCE/env.tar.gz" -C "$RELEASE_DIR/env"
  if [[ -x "$RELEASE_DIR/env/bin/conda-unpack" ]]; then
    PATH="$RELEASE_DIR/env/bin:$PATH" "$RELEASE_DIR/env/bin/conda-unpack"
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

if [[ ! -f /etc/slf-trace/server.env ]]; then
  cp "$RELEASE_DIR/deploy/templates/server.env.example" /etc/slf-trace/server.env
  echo "Created /etc/slf-trace/server.env. Edit DATABASE_* before starting."
fi

ln -sfn "$RELEASE_DIR" "$CURRENT_DIR"
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_ROOT" /etc/slf-trace

(
  cd "$CURRENT_DIR"
  set -a
  # shellcheck disable=SC1091
  source /etc/slf-trace/server.env
  set +a
  "$CURRENT_DIR/env/bin/alembic" -c alembic.ini upgrade head
)

cp "$RELEASE_DIR/deploy/systemd/slf-trace-api.service" /etc/systemd/system/

systemctl daemon-reload
systemctl enable slf-trace-api.service

echo "Installed SLF Track and Trace server release $VERSION at $CURRENT_DIR"
echo "Edit /etc/slf-trace/server.env if needed, then run:"
echo "  systemctl restart slf-trace-api.service"
