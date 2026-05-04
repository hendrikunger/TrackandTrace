# Kiosk Startup

Production panels should open the dedicated kiosk app directly. The admin app stays on `/app`; the
operator kiosk stays on `/kiosk`.

## Station Selection

The kiosk resolves the station in this order:

1. URL parameter: `/kiosk?station_id=1`
2. Environment: `STATION_ID=1`
3. Development fallback: first active station with at least one measurement type

For production, set `STATION_ID` and use a URL with `station_id`. If the configured station is not
active or has no measurement type assigned, the kiosk shows an error instead of silently selecting a
different station.

## Windows 11

Start the Panel service or scheduled task first, then launch Microsoft Edge in kiosk mode for the
station user:

```powershell
$Url = "http://127.0.0.1:5006/kiosk?station_id=1"
Start-Process "msedge.exe" -ArgumentList "--kiosk $Url --edge-kiosk-type=fullscreen --no-first-run"
```

For unattended startup, place that command in a logon scheduled task for the dedicated panel user.
Use Windows Assigned Access when the panel should be locked to Edge.

## Ubuntu 24.04

Start `slf-trace-ui.service`, then launch Chromium for the kiosk session:

```bash
chromium --kiosk --no-first-run --disable-infobars \
  "http://127.0.0.1:5006/kiosk?station_id=1"
```

For unattended startup, add the command to the dedicated user's desktop autostart entry, for
example `~/.config/autostart/slf-trace-kiosk.desktop`:

```ini
[Desktop Entry]
Type=Application
Name=SLF Trace Kiosk
Exec=chromium --kiosk --no-first-run --disable-infobars http://127.0.0.1:5006/kiosk?station_id=1
X-GNOME-Autostart-enabled=true
```

Keep admin access separate by opening `http://127.0.0.1:5006/app` manually with a keyboard/admin
session.
