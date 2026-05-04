# Measuring Station Dashboard Platform

Central browser-based dashboard and measurement capture platform for production measuring stations.

## Goal

The system captures barcode scans and measurement results for individual physical parts, stores them centrally, and gives operators a station UI that can run unattended in kiosk mode.

## Core Decisions

- Python-first stack.
- FastAPI owns APIs, ingestion, validation, WebSockets, auth, and business logic.
- Panel/HoloViz provides the operator, supervisor, and admin UI.
- PostgreSQL is the central database.
- Every measuring station runs a Python companion app.
- Browsers are used for UI only, not as the universal hardware interface layer.
- Windows 11 and Ubuntu 24.04 LTS stations boot into kiosk mode.

## Domain Model

- `rueckmeldenummer` identifies one individual physical part.
- A station represents the physical measuring workplace and its attached measuring machine.
- Initial measurement types use ASCII names in code and German labels in the UI. Measurement
  capture stores these as typed values, so future measurement types do not require a new API
  contract.

| Code / DB field | UI label |
| --- | --- |
| `aussenring` | Außenring |
| `innenring` | Innenring |
| `breite` | Breite |
| `ueberstand` | Überstand |

## Development Status

This repository is in early scaffold development. See `docs/architecture.md` for the implementation
plan. For station workflows, see `docs/workflows.md`. For station kiosk startup, see
`docs/kiosk-startup.md`. For the no-hardware development and CI strategy, including station
simulators, see `docs/test-strategy.md`.

## Start and Test Locally

Use Python 3.12 from WSL. The project is packaged with console scripts, so install it in editable
mode with the development dependencies:

```bash
mamba activate slf_trace
python -m pip install -e ".[dev]"
```

If you are not using Mamba, use any Python 3.12 virtual environment and run the same `pip install`
command inside it.

Create a local `.env` from `.env.example` and set the PostgreSQL password:

```bash
cp .env.example .env
```

Local `.env` files are ignored by git. The important values are:

- `APP_HOST` and `APP_PORT` for the FastAPI server bind address.
- `UI_HOST`, `UI_PORT`, and `UI_AUTORELOAD` for the Panel supervisor/admin UI.
- `DATABASE_HOST`, `DATABASE_PORT`, `DATABASE_NAME`, `DATABASE_USER`, and `DATABASE_PASSWORD` for
  the PostgreSQL database.
- `STATION_ID` and `SERVER_URL` when running a station companion process.

Apply the database schema before using the app against a fresh database:

```bash
alembic upgrade head
```

Start the API:

```bash
slf-trace-api
```

By default, the API listens on `http://localhost:8000`. Useful URLs:

- `http://localhost:8000/health?database=false` checks the service without touching PostgreSQL.
- `http://localhost:8000/health` checks the service and database connection.
- `http://localhost:8000/docs` opens the FastAPI Swagger UI.

Start the supervisor/admin UI in a second terminal:

```bash
slf-trace-ui
```

The UI uses Panel's development server reload mode by default. Set `UI_AUTORELOAD=false` to disable
that behavior. `UI_HOST` defaults to `127.0.0.1` so the browser opens a reachable local URL.

Start the station companion in a separate terminal when testing station-side behavior:

```bash
slf-trace-companion
```

Run the test suite:

```bash
pytest
```

Run linting:

```bash
ruff check .
```

Run both before handing off changes:

```bash
pytest
ruff check .
python -m compileall src tests
```

If `pytest` or `ruff` are missing, the development dependencies were not installed in the active
environment. Re-run `python -m pip install -e ".[dev]"` after activating the intended environment.

See `docs/development.md` for the full development runbook. See `docs/api-contracts.md` for the
initial station companion API contract and `docs/station-inventory.md` for station setup. See
`docs/live-events.md` for WebSocket event payloads and `docs/companion-runtime.md` for the
station-side runtime. See `docs/parser-layer.md` for raw payload parsing and
`docs/measurement-adapters.md` for TCP, serial, and simulator adapter development. UI branding
assets live in `src/slf_trace/ui/assets/`.

Offline production deployment uses packed Python environments. See `docs/deployment.md` and
`deploy/README.md` for the release bundle layout, build steps, and Windows/Ubuntu install scripts.
