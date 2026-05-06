#!/usr/bin/env bash
set -euo pipefail

INSTALL_ROOT="${INSTALL_ROOT:-/opt/slf-trace}"
RELEASE_SOURCE="${1:-.}"
SERVICE_USER="${SERVICE_USER:-slf-trace}"
KIOSK_USER="${KIOSK_USER:-}"
INSTALL_KIOSK="${INSTALL_KIOSK:-false}"

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

if [[ -f "$RELEASE_DIR/deploy/linux/slf-trace-kiosk-browser" ]]; then
  install -o root -g root -m 0755 \
    "$RELEASE_DIR/deploy/linux/slf-trace-kiosk-browser" \
    /usr/local/bin/slf-trace-kiosk-browser
fi

if [[ "$INSTALL_KIOSK" == "true" ]]; then
  if [[ -z "$KIOSK_USER" ]]; then
    echo "Set KIOSK_USER=<desktop-user> when INSTALL_KIOSK=true." >&2
    exit 1
  fi
  if ! id "$KIOSK_USER" >/dev/null 2>&1; then
    useradd --create-home --shell /bin/bash "$KIOSK_USER"
  fi
  kiosk_autostart="/home/$KIOSK_USER/.config/autostart"
  mkdir -p "$kiosk_autostart"
  cp "$RELEASE_DIR/deploy/linux/slf-trace-kiosk.desktop" \
    "$kiosk_autostart/slf-trace-kiosk.desktop"
  chown -R "$KIOSK_USER:$KIOSK_USER" "/home/$KIOSK_USER/.config"

  if [[ -d /etc/gdm3 ]]; then
    cp /etc/gdm3/custom.conf /etc/gdm3/custom.conf.slf-trace-backup 2>/dev/null || true
    python3 - "$KIOSK_USER" <<'PY'
from configparser import ConfigParser
from pathlib import Path
import sys

kiosk_user = sys.argv[1]
path = Path("/etc/gdm3/custom.conf")
config = ConfigParser(strict=False)
config.optionxform = str
config.read(path)
if not config.has_section("daemon"):
    config.add_section("daemon")
config.set("daemon", "AutomaticLoginEnable", "true")
config.set("daemon", "AutomaticLogin", kiosk_user)
with path.open("w", encoding="utf-8") as fh:
    config.write(fh, space_around_delimiters=False)
PY
  else
    echo "GDM not found; kiosk autostart installed, but automatic login was not configured." >&2
  fi
fi

systemctl daemon-reload
systemctl enable slf-trace-ui.service slf-trace-companion.service

echo "Installed SLF Track and Trace panel release $VERSION at $CURRENT_DIR"
echo "Edit /etc/slf-trace/panel.env if needed, then run:"
echo "  systemctl restart slf-trace-ui.service slf-trace-companion.service"
if [[ "$INSTALL_KIOSK" == "true" ]]; then
  echo "Kiosk autostart configured for user $KIOSK_USER. Reboot to validate graphical kiosk startup."
fi
