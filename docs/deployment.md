# Offline Deployment

This project deploys to offline production machines with packed Python environments.
Build artifacts on online build machines, copy the release bundle to production, then install without
internet access.

## Target Artifacts

Build one artifact per target OS and CPU architecture:

- Windows x64 server runtime for API, admin UI, migrations, and PostgreSQL access.
- Linux x64 API runtime for API-only hosts that use an external PostgreSQL server.
- Windows 11 x64 station runtime for station companion and kiosk browser startup.
- Ubuntu 24.04 x64 station runtime for station companion and kiosk browser startup.

Do not cross-pack environments. Build the Windows bundle on Windows and the Ubuntu bundle on
Ubuntu 24.04 or a matching runner/VM.

## Release Bundle Layout

Each release bundle should contain:

```text
slf-trace-release-<version>-<target>/
  VERSION
  SHA256SUMS
  env/ or env.zip/env.tar.gz
  alembic.ini
  migrations/
  deploy/
    install-server.ps1
    install-server.sh
    install-panel.ps1
    install-panel.sh
    linux/
    scripts/
    systemd/
    templates/
  docs/deployment.md
```

The packed environment contains Python, `slf-trace`, and all runtime dependencies. The migrations
are shipped beside the environment because Alembic currently reads `alembic.ini` and `migrations/`
from the application directory.

## Build Steps

1. Start from a clean build VM matching the target OS.
2. Checkout the release source.
3. Run tests and migration checks.
4. Build the project wheel.
5. Create a fresh environment with Python 3.12.
6. Install the wheel with runtime extras needed by the target role: `smb` and `serial`.
7. Smoke-test console entry points.
8. Pack the environment.
9. Assemble release files, config templates, migrations, and checksums.
10. Test the bundle on a clean offline VM.

Use:

- `deploy/scripts/build-packed-env.ps1` on Windows.
- `deploy/scripts/build-packed-env.sh` on Ubuntu 24.04.

## Windows Server Install

Use `deploy/install-server.ps1` on the Windows API/database server.

Responsibilities:

- Unpack or install the packed environment.
- Copy `alembic.ini`, `migrations/`, and config templates.
- Create `.env` from template on first install, or preserve the previous release `.env` during
  updates.
- Set `COMPANION_AUTH_REQUIRED=true` for production unless protected by an
  equivalent deployment control.
- Run `alembic upgrade head` after real PostgreSQL values are configured. On first install the
  installer creates a template `.env` and skips migration; on updates it preserves the existing
  `.env` and runs migration automatically.
- Register startup tasks for:
  - `slf-trace-api`
  - `slf-trace-ui` for the central admin and kiosk UI

PostgreSQL is expected to be installed and managed separately as a Windows service. The `.env`
database settings must point at that PostgreSQL instance.

## Windows 11 Station Install

Use `deploy/install-panel.ps1` on Windows touch panel machines.

Responsibilities:

- Unpack or install the packed environment.
- Create station `.env`.
- Add the station-specific `STATION_TOKEN` generated in the admin UI.
- Register startup for `slf-trace-companion`.
- Configure the browser/kiosk session to open the central UI.

The Windows panel can use built-in Scheduled Tasks, avoiding third-party service wrappers in the
offline environment. The normal production station does not run the Panel UI locally. Use
`-InstallLocalUi` only for temporary diagnostics or fallback operation.

## Ubuntu 24.04 Station Install

Use `deploy/install-panel.sh` on Ubuntu touch panel machines.

Responsibilities:

- Unpack or install the packed environment under `/opt/slf-trace`.
- Create `/etc/slf-trace/panel.env`.
- Add the station-specific `STATION_TOKEN` generated in the admin UI.
- Install, enable, and start `slf-trace-companion.service`.
- Configure the desktop browser to open the central kiosk UI.

The normal production station does not run `slf-trace-ui.service`. The central server runs the API
and Panel UI; the station runs only the companion because scanner and measurement-device access is
local to the touch PC. Use `INSTALL_LOCAL_UI=true` only for temporary development or fallback
diagnostics.

To also configure graphical kiosk boot on a GDM-based Ubuntu desktop, run the installer with:

```bash
sudo INSTALL_KIOSK=true KIOSK_USER=<desktop-user> deploy/install-panel.sh <release-dir>
```

This installs `/usr/local/bin/slf-trace-kiosk-browser`, adds an autostart entry for the kiosk user,
creates `/etc/slf-trace/kiosk.env`, and enables GDM automatic login for that user. The launcher opens:

```text
http://<central-ui-host>:5006/kiosk?station_id=<STATION_ID>
```

using Firefox, Chromium, or Chrome, whichever is installed first in that order.
On GNOME systems the launcher also disables screen blanking and lock activation for the kiosk user.

Keep secrets in `/etc/slf-trace/panel.env`. The desktop kiosk user reads only
`/etc/slf-trace/kiosk.env`, which should contain non-secret browser settings such as:

```dotenv
STATION_ID=3
KIOSK_BASE_URL=http://api.home.io:5006
KIOSK_URL=http://api.home.io:5006/kiosk?station_id=3
```

If you are deliberately reinstalling the same `VERSION` during validation, add
`FORCE_REINSTALL=true`. Production releases should normally use a new version instead.

### Ubuntu Station Build And Validation Runbook

Build the Ubuntu station artifact on an Ubuntu 24.04 x64 build machine with internet access:

```bash
cd TrackandTrace
PATH="$HOME/.local/bin:$PATH" \
MAMBA_ROOT_PREFIX="$HOME/.local/share/mamba" \
TARGET=ubuntu24-x64-panel \
bash deploy/scripts/build-packed-env.sh
```

If `micromamba` is missing on the build machine, install it first:

```bash
mkdir -p "$HOME/.local/bin" "$HOME/.local/micromamba"
curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest -o /tmp/micromamba.tar.bz2
tar -xjf /tmp/micromamba.tar.bz2 -C "$HOME/.local/micromamba"
ln -sfn "$HOME/.local/micromamba/bin/micromamba" "$HOME/.local/bin/micromamba"
```

Validate the artifact before copying it to a station:

```bash
cd dist/offline/<version>/ubuntu24-x64-panel
sha256sum -c SHA256SUMS
find . -maxdepth 3 -type f | sort
```

The bundle must include:

- `env.tar.gz`
- `VERSION`
- `SHA256SUMS`
- `alembic.ini`
- `migrations/`
- `deploy/install-panel.sh`
- `deploy/linux/slf-trace-kiosk-browser`
- `deploy/linux/slf-trace-kiosk.desktop`
- `deploy/systemd/slf-trace-companion.service`
- `deploy/templates/panel.env.example`
- `docs/deployment.md`
- `docs/security.md`

Copy the artifact to the Ubuntu panel:

```bash
rsync -az dist/offline/<version>/ubuntu24-x64-panel/ \
  <station-user>@<station-host>:/tmp/slf-trace-ubuntu24-x64-panel/
```

Install the release and configure graphical kiosk startup:

```bash
ssh <station-user>@<station-host>
sudo INSTALL_KIOSK=true \
  KIOSK_USER=<desktop-user> \
  /tmp/slf-trace-ubuntu24-x64-panel/deploy/install-panel.sh \
  /tmp/slf-trace-ubuntu24-x64-panel
```

For repeated validation of the same `VERSION`, add `FORCE_REINSTALL=true` to the install command.

Edit `/etc/slf-trace/panel.env` before starting the services. Minimum values:

```dotenv
APP_ENV=production
SERVER_URL=http://api.home.io:8000
STATION_ID=<station-id>
STATION_TOKEN=<token-if-api-token-enforcement-is-enabled>
DATABASE_HOST=<postgres-host>
DATABASE_PORT=5432
DATABASE_NAME=<database-name>
DATABASE_USER=<database-user>
DATABASE_PASSWORD=<database-password>
COMPANION_STATE_PATH=/opt/slf-trace/state/companion_state.sqlite3
COMPANION_LOG_PATH=/opt/slf-trace/logs/slf-trace-companion.log
```

Edit `/etc/slf-trace/kiosk.env` for the desktop browser autostart:

```dotenv
STATION_ID=<station-id>
KIOSK_BASE_URL=http://api.home.io:5006
KIOSK_URL=http://api.home.io:5006/kiosk?station_id=<station-id>
```

Start and validate services:

```bash
sudo systemctl restart slf-trace-companion.service
systemctl is-active slf-trace-companion.service
systemctl is-enabled slf-trace-companion.service
systemctl is-enabled slf-trace-ui.service || true
curl --max-time 20 -fsS "http://api.home.io:5006/kiosk?station_id=<station-id>" >/tmp/kiosk.html
journalctl -u slf-trace-companion.service --since "2 minutes ago" --no-pager
```

Reboot validation:

```bash
sudo reboot
```

After the station returns:

```bash
systemctl is-active slf-trace-companion.service display-manager
systemctl is-active slf-trace-ui.service || true
curl --max-time 20 -fsS "http://api.home.io:5006/kiosk?station_id=<station-id>" >/tmp/kiosk.html
pgrep -af "firefox|chromium|chrome|slf-trace-kiosk"
loginctl list-sessions --no-legend
journalctl -u slf-trace-companion.service --since "5 minutes ago" --no-pager
```

Expected result:

- `slf-trace-companion.service` is active after boot
- `slf-trace-ui.service` is inactive or disabled on the station unless `INSTALL_LOCAL_UI=true`
- `display-manager` is active
- central kiosk URL returns HTML with `curl`
- Firefox, Chromium, or Chrome runs with the kiosk URL
- companion sends heartbeats to the API
- scanner startup commands are visible in the companion journal when scanner adapter is enabled

End-to-end station validation:

1. Configure the station in the admin UI with the real station ID, scanner adapter, and measurement adapter.
2. Restart `slf-trace-companion.service` and confirm the scanner enters working mode.
3. Scan a Rückmeldenummer in the kiosk.
4. Confirm the companion receives one measurement request, queries the measurement device, and uploads the value.
5. Confirm the value appears in the admin measurement history for the selected station.

For a temporary TCP measurement simulator on another machine:

```bash
nc -lk 0.0.0.0 55169
```

When the station sends the configured query, enter a plain numeric value followed by Return.

## Offline Update

1. Stop services/tasks.
2. Keep the previous release directory intact for rollback.
3. Unpack the new release to a versioned directory.
4. Update the `current` link or install path.
5. Run `alembic upgrade head` on the Windows server.
6. Restart services/tasks.
7. Run smoke checks.

## Rollback

1. Stop services/tasks.
2. Point `current` back to the previous release directory or restore the previous install path.
3. Restart services/tasks.
4. Run smoke checks.

Database rollback is not automatic. Prefer forward-only migrations in production unless a tested
downgrade procedure exists for the specific release.

## Test Server Update

The current `api.home.io` test server intentionally uses a git checkout instead of the offline
release layout. This keeps the pilot machine easy to update while the application is still moving
quickly.

Use `deploy/update-test-server.sh` on the API VM:

```bash
cd /opt/slf-trace/src/TrackandTrace
git status --short
sudo deploy/update-test-server.sh
```

On `api.home.io` the same script is installed as:

```bash
sudo slf-trace-update-server
```

The script:

- fetches and fast-forwards the configured branch, defaulting to `origin/main`
- refuses to continue if the server checkout has local changes
- reinstalls the package into `/opt/slf-trace/env`
- runs `alembic upgrade head`
- restarts `slf-trace-api.service` and `slf-trace-ui.service`
- writes an update log under `/opt/slf-trace/logs/`
- runs a local API health check

This update route is for the online test server only. Offline production should use versioned
release bundles so rollback is just a `current` link switch plus service restart.

## Test Station Update

Online test stations can also update from a git checkout. This is only for pilot/test machines; the
offline production station install still uses packed release bundles.

Use `deploy/update-test-station.sh` on the station:

```bash
cd /opt/slf-trace/src/TrackandTrace
git status --short
sudo deploy/update-test-station.sh
```

The script:

- fetches and fast-forwards the configured branch, defaulting to `origin/main`
- refuses to continue if the station checkout has local changes
- reinstalls the package into the existing station environment with `smb` and `serial` extras
- refreshes `/usr/local/bin/slf-trace-kiosk-browser` from the checkout
- restarts `slf-trace-companion.service`
- runs a companion service check and central kiosk URL smoke check when `SERVER_URL` and `STATION_ID`
  are configured

## Windows Server Build

Build Windows server artifacts on a Windows x64 machine that has internet access and matches the
production runtime class. Do not build the Windows packed environment from Linux or macOS.

Required build tools on the Windows build host:

- Miniforge/Mambaforge, micromamba, mamba, or conda for Windows x64.
- Python is not required on `PATH` before the build. The build script creates the target Python
  3.12 environment and builds the wheel inside it.
- Git checkout at the intended release commit.

Recommended first-pass build command:

```powershell
powershell -ExecutionPolicy Bypass -File deploy\scripts\build-packed-env.ps1 `
  -Target windows-x64-server
```

If the packer is not on `PATH`, pass it explicitly:

```powershell
powershell -ExecutionPolicy Bypass -File deploy\scripts\build-packed-env.ps1 `
  -Target windows-x64-server `
  -MambaExe C:\Users\<user>\miniforge3\Scripts\mamba.exe
```

The output is written to:

```text
dist\offline\<version>\windows-x64-server\
```

Before accepting the artifact, validate:

- `SHA256SUMS` exists and contains `env.zip`, `alembic.ini`, and `VERSION`
- `deploy\install-server.ps1` is present in the bundle
- `deploy\templates\server.env.example` is present
- `docs\deployment.md` and `docs\security.md` are present
- `RELEASE_NOTES.md` exists and records target/build metadata
- `env\Scripts\slf-trace-api.exe` works after unpacking on a clean Windows VM
- `env\Scripts\alembic.exe -c alembic.ini upgrade head` works against a test database

The Windows production install uses `deploy\install-server.ps1`. It should preserve existing
configuration, run migrations, and register or update the Windows Scheduled Tasks for the API and
central Panel UI.
On first install, it creates a template `.env` and skips migration until the operator configures the
real PostgreSQL values.

## Windows Server Offline Install Runbook

1. Copy `dist\offline\<version>\windows-x64-server\` to the offline Windows server.
2. Verify checksums from inside the release directory:

   ```powershell
   Get-Content SHA256SUMS | ForEach-Object {
     $parts = $_ -split "\s+", 2
     $actual = (Get-FileHash $parts[1] -Algorithm SHA256).Hash.ToLower()
     if ($actual -ne $parts[0]) { throw "Checksum mismatch: $($parts[1])" }
   }
   ```

3. Install or update:

   ```powershell
   powershell -ExecutionPolicy Bypass -File deploy\install-server.ps1 `
     -InstallRoot C:\SLF\TrackTrace `
     -ReleaseSource .
   ```

   The server installer creates both the API task and the central UI task by default. Use `-SkipUi`
   only for exceptional API-only diagnostics.

4. Edit `C:\SLF\TrackTrace\current\.env` before starting services. Production values must include
   the PostgreSQL connection and `COMPANION_AUTH_REQUIRED=true`. On updates, the installer copies
   the previous release `.env` into the new release before switching `current`.
5. Run migration manually after first-install configuration if the installer reports that it
   created a template `.env` and skipped migration:

   ```powershell
   cd C:\SLF\TrackTrace\current
   .\env\Scripts\alembic.exe -c alembic.ini upgrade head
   ```

6. Start or restart the Scheduled Tasks:

   ```powershell
   Start-ScheduledTask -TaskName "SLF Track Trace API"
   ```

   ```powershell
   Start-ScheduledTask -TaskName "SLF Track Trace UI"
   ```

7. Smoke check:

   ```powershell
   Invoke-WebRequest http://localhost:8000/health?database=false
   Invoke-WebRequest http://localhost:8000/health
   ```

   ```powershell
   Invoke-WebRequest http://localhost:5006/app
   ```

## Windows Rollback

1. Stop `SLF Track Trace API` and `SLF Track Trace UI` Scheduled Tasks.
2. Remove the `C:\SLF\TrackTrace\current` junction.
3. Recreate the junction to the previous version:

   ```powershell
   New-Item -ItemType Junction `
     -Path C:\SLF\TrackTrace\current `
     -Target C:\SLF\TrackTrace\releases\<previous-version>
   ```

4. Start the Scheduled Tasks and repeat the smoke checks.

Database rollback is not automatic. Only run a database downgrade when that release has a tested
downgrade procedure.

## Smoke Checks

Server:

```powershell
Invoke-WebRequest http://localhost:8000/health?database=false
Invoke-WebRequest http://localhost:8000/health
```

Central UI:

```text
http://<server-host>:5006/app
http://<server-host>:5006/kiosk?station_id=1
```

Companion:

- Confirm rotating logs are written to `COMPANION_LOG_PATH`.
- Confirm invalid station tokens are rejected if `COMPANION_AUTH_REQUIRED=true`.
- Confirm station heartbeat appears in the admin UI.
- Confirm scanner/adapter health appears in the admin health column.

## Data To Collect For Support

- `.env` with secrets redacted.
- `logs/slf-trace-companion.log*`
- API logs from the Windows server task/service.
- `alembic current` output.
- Admin station health screenshot.
- Recent diagnostics from `/api/stations/{station_id}/events`.
