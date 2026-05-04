# Offline Deployment

This project deploys to offline production machines with packed Python environments.
Build artifacts on online build machines, copy the release bundle to production, then install without
internet access.

## Target Artifacts

Build one artifact per target OS and CPU architecture:

- Windows x64 server runtime for API, admin UI, migrations, and PostgreSQL access.
- Windows 11 x64 panel runtime for kiosk/admin Panel UI and station companion.
- Ubuntu 24.04 x64 panel runtime for kiosk/admin Panel UI and station companion.

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
    install-panel.ps1
    install-panel.sh
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
- Create or update `.env`.
- Run `alembic upgrade head`.
- Register startup tasks for:
  - `slf-trace-api`
  - optionally `slf-trace-ui` for admin access on the server

PostgreSQL is expected to be installed and managed separately as a Windows service. The `.env`
database settings must point at that PostgreSQL instance.

## Windows 11 Panel Install

Use `deploy/install-panel.ps1` on Windows panel machines.

Responsibilities:

- Unpack or install the packed environment.
- Create station `.env`.
- Register startup tasks for:
  - `slf-trace-ui`
  - `slf-trace-companion`

The Windows panel can use built-in Scheduled Tasks, avoiding third-party service wrappers in the
offline environment.

## Ubuntu 24.04 Panel Install

Use `deploy/install-panel.sh` on Ubuntu panel machines.

Responsibilities:

- Unpack or install the packed environment under `/opt/slf-trace`.
- Create `/etc/slf-trace/panel.env`.
- Install `systemd` units:
  - `slf-trace-ui.service`
  - `slf-trace-companion.service`
- Enable and start both services.

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

## Smoke Checks

Server:

```powershell
Invoke-WebRequest http://localhost:8000/health?database=false
Invoke-WebRequest http://localhost:8000/health
```

Panel:

```text
http://127.0.0.1:5006/app
http://127.0.0.1:5006/kiosk
```

Companion:

- Confirm rotating logs are written to `COMPANION_LOG_PATH`.
- Confirm station heartbeat appears in the admin UI.
- Confirm scanner/adapter health appears in the admin health column.

## Data To Collect For Support

- `.env` with secrets redacted.
- `logs/slf-trace-companion.log*`
- API logs from the Windows server task/service.
- `alembic current` output.
- Admin station health screenshot.
- Recent diagnostics from `/api/stations/{station_id}/events`.
