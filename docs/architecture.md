# Architecture

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
- `location`
- `scanner_host`
- `scanner_port`
- `scanner_protocol`
- `workflow_type`
- `workflow_title`
- `workflow_config`
- `adapter_config`
- `companion_token_hash`
- `payload_format`
- `timing_notes`
- `network_notes`
- `active`
- `created_at`
- `updated_at`

`workflow_type` is the runtime/UI switch for station processes. Measurement stations use
`measurement_capture`; label-printing and laser-marking stations can exist without fake measurement
types. `adapter_config` stores hardware adapter definitions for the station companion. The raw
station token is shown once in the admin UI and only its hash is stored in `companion_token_hash`.

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

`station_id` plus `idempotency_key` is unique so companion retries do not duplicate measurements.

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

Scanner barcode scans are also retained here when a raw payload is supplied. Kiosk measurement
requests are represented as `source_type="measurement_request"` raw payload rows so the companion
can poll and collect adapter values for the scanned Rückmeldenummer.

### `station_heartbeats`

One row per companion heartbeat.

- `id`
- `station_id`
- `status`
- `hostname`
- `companion_version`
- `adapter_status`
- `received_at`

### `station_events`

Central diagnostics emitted by stations or parser/API failures.

- `id`
- `station_id`
- `event_type`
- `severity`
- `message`
- `context`
- `occurred_at`

## Companion App

The companion app is installed on every station.

Responsibilities:

- Listen for Keyence SR-X scanner connections on the station scanner port.
- Connect to measuring machine interfaces.
- Handle SMB1 on Ubuntu 24.04 LTS using `pysmb`.
- Poll SMB files or listen to TCP/serial streams.
- Parse or forward raw payloads.
- Maintain local SQLite outbox.
- Retry submissions after network outages.
- Send heartbeat and adapter status.
- Report version and health state.
- Poll barcode-created measurement requests and aggregate adapter values for the active
  Rückmeldenummer.
- Send station diagnostics events for configuration, adapter, parser, and partial-measurement
  failures.

## Adapter Types

Built-in adapter targets:

- Keyence SR-X TCP barcode scanner listener
- SMB1 polling adapter with `pysmb`
- Generic TCP/IP measurement adapter
- Serial request/response measurement adapter
- Simulator/manual test adapter

The companion builds SMB, TCP, and serial adapters from station `adapter_config`. It also builds the
Keyence scanner listener from station scanner fields. See `docs/measurement-adapters.md`.

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

1. Foundations: station inventory, database schema, FastAPI API contracts, persistence,
   idempotency, WebSockets.
2. Companion and integrations: companion runtime, Keyence SR-X TCP scanner listener, SMB1 via
   `pysmb`, TCP/IP and serial request interfaces, parser layer.
3. Operator UI and kiosk: Panel kiosk UI, supervisor/admin UI, Windows 11 kiosk, Ubuntu 24.04 kiosk.
4. Pilot hardening: companion token auth, diagnostics, deployment packaging, automated tests,
   simulators, pilot validation.

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
