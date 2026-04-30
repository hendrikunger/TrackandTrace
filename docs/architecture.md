# Architecture and Implementation Plan

## Runtime Architecture

```text
Keyence SR-X scanner
  -> TCP/IP
  -> station companion app
  -> central FastAPI API
  -> part created/resolved by rueckmeldenummer
  -> browser UI updated via WebSocket

Measuring device
  -> SMB1 / SMB2 / TCP/IP / serial / file
  -> station companion app adapter
  -> parser layer
  -> central FastAPI API
  -> PostgreSQL measurement row + raw payload traceability
```

## Initial Database Schema

### `stations`

One row per physical measuring workplace.

- `id`
- `name`
- `hostname`
- `location`
- `operating_system`
- `machine_name`
- `machine_type`
- `measurement_interface`
- `scanner_host`
- `scanner_port`
- `scanner_protocol`
- `payload_format`
- `timing_notes`
- `network_notes`
- `active`
- `created_at`
- `updated_at`

### `parts`

One row per individual physical part.

- `id`
- `rueckmeldenummer`, unique barcode value
- `created_at`
- `updated_at`

### `measurements`

One row per captured measurement event.

- `id`
- `part_id`
- `station_id`
- `result_status`
- `measured_at`
- `source_type`
- `raw_payload_id`
- `idempotency_key`
- `created_at`

### `measurement_values`

One row per measured value in a measurement event.

- `id`
- `measurement_id`
- `measurement_type`, for example `aussenring`, `innenring`, `breite`, `ueberstand`
- `value`
- `unit`
- `result_status`

### `measurement_types`

Controlled catalog of allowed measurement value types.

- `code`, for example `aussenring`, `innenring`, `breite`, `ueberstand`
- `label`, localized UI label
- `unit`
- `active`
- `created_at`

### `station_measurement_types`

Allowed measurement types per station.

- `station_id`
- `measurement_type_code`
- `active`

### `raw_payloads`

Original scanner/device/file payloads for traceability and parser debugging.

- `id`
- `station_id`
- `source_type`
- `payload_hash`
- `content`
- `received_at`

## Companion App

The companion app is installed on every station.

Responsibilities:

- Listen for Keyence SR-X scanner connections on the station scanner port.
- Connect to measuring machine interfaces.
- Handle SMB1 on Ubuntu 24.04 LTS using `pysmb`.
- Poll files or listen to TCP/serial streams.
- Parse or forward raw payloads.
- Maintain local SQLite outbox.
- Retry submissions after network outages.
- Send heartbeat and adapter status.
- Report version and health state.

## Adapter Types

Initial adapter targets:

- Keyence SR-X TCP barcode scanner listener
- SMB1 polling adapter with `pysmb`
- Generic TCP/IP measurement adapter
- Generic serial measurement adapter
- File/directory polling adapter
- Simulator/manual test adapter

The current companion scaffold includes the shared adapter lifecycle plus simulator, TCP line,
serial line, and SMB1 polling adapter foundations. See `docs/measurement-adapters.md`.

## Kiosk Startup

### Windows 11

- Dedicated local kiosk user.
- Companion app runs as Windows service or supervised background process.
- Microsoft Edge launches in kiosk mode using Assigned Access.
- Station dashboard opens automatically after boot.

### Ubuntu 24.04 LTS

- Dedicated local kiosk user.
- GDM automatic login.
- Companion app runs as `systemd` service.
- Chromium/Chrome launches in kiosk mode with station dashboard URL.
- Ubuntu is preferred for legacy SMB1 access where Windows 11 is unreliable.

## Milestones

1. Foundations: station inventory, database schema, FastAPI skeleton, API contracts, persistence, idempotency, WebSockets.
2. Companion and integrations: companion runtime, Keyence SR-X TCP scanner listener, SMB1 via `pysmb`, TCP/IP and serial interfaces, parser layer.
3. Operator UI and kiosk: Panel station UI, supervisor/admin UI, Windows 11 kiosk, Ubuntu 24.04 kiosk.
4. Pilot hardening: auth, diagnostics, deployment packaging, automated tests, simulators, pilot validation.

## Pilot Success Criteria

A pilot station is accepted when:

- It boots unattended into the dashboard UI.
- Companion app starts automatically.
- Keyence SR-X scanner submits a barcode over TCP/IP to the companion listener on the station scanner port.
- The barcode creates or resolves the correct part by `rueckmeldenummer`.
- The measuring device produces one or more typed measurement values.
- Dedicated stations can produce one measurement value, such as only `breite` or only `ueberstand`.
- Measurement types are known to the server and enabled per station.
- Measurement is persisted centrally.
- Raw payload is retained for traceability.
- Temporary network interruption does not lose data.
- Supervisor UI shows station health and measurement history.
