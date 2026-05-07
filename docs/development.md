# Development Runbook

## Environment

Current local Codex/macOS development environment:

```bash
cd /Users/unhe/gitRepos/TrackandTrace
/Users/unhe/miniforge3/bin/mamba activate slf
python --version
```

Run commands through the environment when a non-interactive shell is used:

```bash
/Users/unhe/miniforge3/bin/mamba run -n slf pytest
/Users/unhe/miniforge3/bin/mamba run -n slf ruff check .
```

Older Windows/WSL development environments may still use:

```bash
cd /mnt/c/Users/unger/gitRepos/TrackandTrace
mamba activate slf_trace
python --version
```

Install or refresh project dependencies:

```bash
python -m pip install -e ".[dev]"
```

## Local Configuration

Create a local `.env` file:

```bash
cp .env.example .env
```

Set the PostgreSQL password in `.env`. Local `.env` files are ignored by git.

## Shared Test Environment

These hosts are the current lab/test environment. Credentials here are for isolated test systems
only; do not reuse them for production.

### Database

- Host: `postgres.home.io`
- IP: `10.0.0.70`
- Port: `5432`
- Database: `trackandtrace_dev`
- User: `trackandtrace_admin`
- Password: `trackandtrace_admin`

Use this connection for local, API VM, and station tests unless a task explicitly says otherwise.

### API VM

- Host: `api.home.io`
- SSH user: `unhe`
- Sudo password: `apitest`
- Repo checkout: `/opt/slf-trace/src/TrackandTrace`
- Python environment: `/opt/slf-trace/env`
- API service: `slf-trace-api.service`
- UI service: `slf-trace-ui.service`
- Public admin UI: `http://api.home.io:5006/app`
- Public kiosk UI: `http://api.home.io:5006/kiosk`
- API health: `http://api.home.io:8000/health`

Connect:

```bash
ssh unhe@api.home.io
```

Update the API VM from git and restart services:

```bash
cd /opt/slf-trace/src/TrackandTrace
echo apitest | sudo -S -p "" deploy/update-test-server.sh
```

Use this for API, admin UI, and kiosk UI changes. Do not SSH to or restart the station for UI-only
changes; the kiosk is served centrally from `api.home.io`.

Check service state:

```bash
systemctl status slf-trace-api.service
systemctl status slf-trace-ui.service
journalctl -u slf-trace-api.service -n 100 --no-pager
journalctl -u slf-trace-ui.service -n 100 --no-pager
```

### Ubuntu Test Station

- Host/IP: `10.0.0.197`
- SSH user: `u1`
- Sudo password: `u1`
- Repo checkout: `/opt/slf-trace/src/TrackandTrace`
- Packaged/current environment: `/opt/slf-trace/current/env`
- Companion service: `slf-trace-companion.service`
- Kiosk service: `slf-trace-kiosk.service`
- Default assigned station: `BREITE-DEV-01`
- Default station id in test database: `3`
- Server URL: `http://api.home.io:8000`

Connect:

```bash
ssh u1@10.0.0.197
```

Update the station from git and restart the companion/kiosk services only when station-side code or
service setup changed, for example scanner, measurement adapters, companion runtime, kiosk browser
launcher, or systemd units. Do not run this for API, admin UI, or central kiosk UI changes.

```bash
cd /opt/slf-trace/src/TrackandTrace
echo u1 | sudo -S -p "" deploy/update-test-station.sh
```

Check service state:

```bash
systemctl status slf-trace-companion.service
systemctl status slf-trace-kiosk.service
journalctl -u slf-trace-companion.service -n 100 --no-pager
journalctl -u slf-trace-kiosk.service -n 100 --no-pager
```

Restart only the companion:

```bash
echo u1 | sudo -S -p "" systemctl restart slf-trace-companion.service
```

### Test Hardware And Simulators

Keyence scanner:

- IP: `172.16.2.20`
- Port: `9004`
- Working mode command: `LON\r\n`
- Off command: `LOFF\r\n`

Demo TCP measurement server:

- Host: `10.0.0.107`
- Port: `55169`
- Query command from station: `?\r`
- The response may be a bare value, for example `32,2`.

TrueNAS SMB test share:

- Server: `truenas.home.io`
- Share path: `//truenas.home.io/agents/ExcelAusgabe`
- User: `ai-agent`
- Password: `hnbcZLqu5q8B50D5N068wp`
- Test behavior: the SMB adapter reads CSV files and deletes them after a successful read.

Current multi-adapter test station setup:

- SMB adapter `smb-truenas-test` provides measurement type `breite`.
- TCP adapter `tcp-test` provides measurement type `innenring`.
- A barcode starts one collection request. Each adapter should stop polling after its own value has
  been received. The multi-adapter request timeout is five minutes.

## Database Tools

Check PostgreSQL connectivity:

```bash
PGPASSWORD=trackandtrace_admin psql \
  -d "host=10.0.0.70 port=5432 dbname=trackandtrace_dev user=trackandtrace_admin" \
  -c "select current_database(), current_user;"
```

Apply migrations:

```bash
alembic upgrade head
```

Show the current migration:

```bash
alembic current
```

Check ORM/schema drift:

```bash
alembic check
```

List tables:

```bash
PGPASSWORD=trackandtrace_admin psql \
  -d "host=10.0.0.70 port=5432 dbname=trackandtrace_dev user=trackandtrace_admin" \
  -c "\dt"
```

## Run the API

Start FastAPI:

```bash
slf-trace-api
```

Useful URLs:

- `http://localhost:8000/health?database=false`
- `http://localhost:8000/health`
- `http://localhost:8000/docs`

Equivalent explicit command:

```bash
python -m uvicorn slf_trace.api.main:app --host 0.0.0.0 --port 8000 --reload
```

## Run the UI

Start the Panel supervisor/admin UI:

```bash
slf-trace-ui
```

The console script starts Panel with `panel serve --dev` by default, so the browser reloads when UI
code or imported project modules change. The UI binds to `UI_HOST` and `UI_PORT`, which default to
`127.0.0.1:5006`. Keep `UI_HOST=127.0.0.1` for local development so Panel opens a reachable browser
URL; use `0.0.0.0` only when you intentionally want to bind the UI on all interfaces. Set
`UI_AUTORELOAD=false` in `.env` to disable Panel development reload behavior. The launcher also
passes the matching `--allow-websocket-origin`, because Bokeh rejects websocket connections when the
browser origin does not exactly match the allowed host and port.

The admin UI is available at `/app`. The production operator UI is available separately at
`/kiosk`, and can be pinned to a station with `/kiosk?station_id=1`. The URL station id overrides
`STATION_ID` for local development. See `docs/kiosk-startup.md` for Windows and Ubuntu kiosk browser
startup commands.

In the station admin view, station detail fields and measurement type assignments autosave when a
value changes. Select a station in the read-only station table, edit the controls below it, and
watch the status message for the autosave result. Tables are read-only and scroll in place instead
of using pagination controls, which keeps the layout usable on narrower browser widths.

The measurement history view searches by `Rückmeldenummer` and can optionally narrow results to one
station. Selecting a measurement with a linked raw payload loads the raw payload detail
automatically; the raw payload ID input remains available for direct debugging lookup.

Static branding and other user-facing images live in `src/slf_trace/ui/assets/`. Load them through
`importlib.resources` so Panel UIs can reuse them without hard-coded paths.

## Run the Companion Placeholder

Start the station companion runtime:

```bash
slf-trace-companion
```

For station-specific tests, set these in `.env` first:

```env
STATION_ID=1
SERVER_URL=http://localhost:8000
COMPANION_STATE_PATH=companion_state.sqlite3
```

Companion measurement adapters live in `src/slf_trace/companion/adapters`. See
`docs/measurement-adapters.md` for the adapter lifecycle, simulator usage, TCP line adapter, and
serial line adapter.

For legacy SMB1 station work, install the optional dependency in the active environment:

```bash
python -m pip install -e ".[smb]"
```

The station host also needs the `smbclient` command line tool if delete-after-processing uses the
fallback delete path.

For serial measuring devices, install the optional dependency:

```bash
python -m pip install -e ".[serial]"
```

## Test and Lint

Run tests:

```bash
pytest
```

Run linting:

```bash
ruff check .
```

Run the normal pre-handoff checks:

```bash
ruff check .
pytest
alembic check
```

The no-hardware test strategy and simulator commands live in `docs/test-strategy.md`.

## Smoke Test Calls

Create a station with a single allowed measurement type:

```bash
curl -X POST http://localhost:8000/api/stations \
  -H "Content-Type: application/json" \
  -d '{
    "name": "BREITE-DEV-02",
    "location": "Development",
    "scanner_host": "10.0.0.21",
    "scanner_port": 9004,
    "scanner_protocol": "Keyence SR-X TCP",
    "adapter_config": [
      {
        "type": "smb1_polling",
        "server": "10.0.0.50",
        "share": "MEASURE",
        "username_env": "SMB_USER",
        "password_env": "SMB_PASSWORD",
        "remote_dir": "/ExcelAusgabe",
        "measurement_type": "breite",
        "value_column_index": 13
      }
    ],
    "payload_format": "CSV: rueckmeldenummer,breite",
    "measurement_type_codes": ["breite"]
  }'
```

Fetch companion station config:

```bash
curl http://localhost:8000/api/companion/stations/1/config
```

Send a heartbeat:

```bash
curl -X POST http://localhost:8000/api/companion/heartbeats \
  -H "Content-Type: application/json" \
  -d '{
    "station_id": 1,
    "status": "online",
    "companion_version": "dev",
    "adapter_status": {"simulator": "online"}
  }'
```

Submit a barcode scan:

```bash
curl -X POST http://localhost:8000/api/companion/barcode-scans \
  -H "Content-Type: application/json" \
  -d '{
    "station_id": 1,
    "rueckmeldenummer": "DEV-RM-0001",
    "source_type": "keyence_srx",
    "raw_payload": "RM-DEV-0001",
    "scanned_at": "2026-04-29T15:00:00+02:00"
  }'
```

For a station with a Keyence SR-X scanner, the companion listens on `scanner_port` and forwards
incoming scan lines to this endpoint. `scanner_host` is the expected scanner IP address when you
want to restrict which peer can connect.

Submit a raw payload:

```bash
curl -X POST http://localhost:8000/api/companion/raw-payloads \
  -H "Content-Type: application/json" \
  -d '{
    "station_id": 1,
    "source_type": "simulator",
    "content": "breite=7.7"
  }'
```

Submit a measurement:

```bash
curl -X POST http://localhost:8000/api/companion/measurements \
  -H "Content-Type: application/json" \
  -d '{
    "station_id": 1,
    "idempotency_key": "dev-event-0001",
    "source_type": "simulator",
    "measured_at": "2026-04-28T11:30:00Z",
    "result_status": "pass",
    "rueckmeldenummer": "DEV-RM-0001",
    "values": [
      {
        "measurement_type": "breite",
        "value": "7.7",
        "unit": "mm",
        "result_status": "pass"
      }
    ]
  }'
```

## WebSocket Smoke Test

Start the API in one terminal, then run this in another:

```bash
python - <<'PY'
import asyncio
import json
from websockets.asyncio.client import connect

async def main():
    async with connect("ws://localhost:8000/api/live/events") as websocket:
        print(json.dumps(json.loads(await websocket.recv()), indent=2))

asyncio.run(main())
PY
```

Then submit a heartbeat, barcode scan, raw payload, or measurement through the API. The WebSocket
client should print the live event.
