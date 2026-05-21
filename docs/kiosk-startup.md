# Kiosk Startup

Production panels should open the dedicated kiosk app directly. The admin app stays on `/app`; the
operator kiosk stays on `/kiosk`.

## Station Selection

The kiosk resolves the station in this order:

1. URL parameter: `/kiosk?station_id=1`
2. Environment: `STATION_ID=1`
3. Development fallback: first active kiosk-eligible station

For production, set `STATION_ID` and use a URL with `station_id`. If the configured station is not
active, the kiosk shows an error instead of silently selecting a different station. Measurement
capture stations must also have at least one effective measurement type, usually through enabled
adapter `measurement_type` settings. Non-measurement workflows such as `label_printing` and
`laser_marking` can open without measurement types.

## Windows 11

Open the central server UI in Microsoft Edge kiosk mode for the station user. Do not start a local
Panel UI on production stations.

```powershell
$Url = "http://<server-host>:8080/kiosk?station_id=1"
Start-Process "msedge.exe" -ArgumentList "--kiosk $Url --edge-kiosk-type=fullscreen --no-first-run"
```

For unattended startup, register a logon scheduled task for the dedicated panel user. The browser
must run as the interactive panel user, not as `SYSTEM`.

```powershell
$TaskName = "SLF Track Trace Kiosk Browser"
$KioskUser = "<domain-or-machine>\<panel-user>"
$Url = "http://<server-host>:8080/kiosk?station_id=1"
$Edge = "$env:ProgramFiles(x86)\Microsoft\Edge\Application\msedge.exe"
if (-not (Test-Path $Edge)) {
  $Edge = "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe"
}

$Action = New-ScheduledTaskAction `
  -Execute $Edge `
  -Argument "--kiosk $Url --edge-kiosk-type=fullscreen --no-first-run"
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $KioskUser
$Principal = New-ScheduledTaskPrincipal -UserId $KioskUser -LogonType Interactive

Register-ScheduledTask `
  -TaskName $TaskName `
  -Action $Action `
  -Trigger $Trigger `
  -Principal $Principal `
  -Force
```

Manage the task:

```powershell
Get-ScheduledTask "SLF Track Trace Kiosk Browser"
Start-ScheduledTask "SLF Track Trace Kiosk Browser"
Stop-ScheduledTask "SLF Track Trace Kiosk Browser"
```

Use Windows Assigned Access when the panel should be locked to Edge. Assigned Access is separate
from the companion startup task; the companion is registered by `deploy\install-panel.ps1` as
`SLF Track Trace Companion` and runs at system startup as `SYSTEM`.

## Ubuntu 24.04

Launch the central server UI for the kiosk session. The station runs `slf-trace-companion.service`
locally, but does not run `slf-trace-ui.service` in production.

```bash
chromium --kiosk --no-first-run --disable-infobars \
  "http://<server-host>:8080/kiosk?station_id=1"
```

For unattended startup, add the command to the dedicated user's desktop autostart entry, for
example `~/.config/autostart/slf-trace-kiosk.desktop`:

```ini
[Desktop Entry]
Type=Application
Name=SLF Trace Kiosk
Exec=chromium --kiosk --no-first-run --disable-infobars http://<server-host>:8080/kiosk?station_id=1
X-GNOME-Autostart-enabled=true
```

Keep admin access separate by opening `http://<server-host>:8080/app` manually with a
keyboard/admin session.
