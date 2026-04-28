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
- `machine_name`
- `machine_type`
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
- `aussenring`
- `innenring`
- `breite`
- `ueberstand`
- `result_status`
- `measured_at`
- `source_type`
- `raw_payload_id`
- `created_at`

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

- Connect to Keyence SR-X scanner over TCP/IP.
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

- Keyence SR-X TCP barcode scanner
- SMB1 polling adapter with `pysmb`
- Generic TCP/IP measurement adapter
- Generic serial measurement adapter
- File/directory polling adapter
- Simulator/manual test adapter

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
2. Companion and integrations: companion runtime, Keyence SR-X TCP scanner, SMB1 via `pysmb`, TCP/IP and serial interfaces, parser layer.
3. Operator UI and kiosk: Panel station UI, supervisor/admin UI, Windows 11 kiosk, Ubuntu 24.04 kiosk.
4. Pilot hardening: auth, diagnostics, deployment packaging, automated tests, simulators, pilot validation.

## Pilot Success Criteria

A pilot station is accepted when:

- It boots unattended into the dashboard UI.
- Companion app starts automatically.
- Keyence SR-X scanner submits a barcode over TCP/IP.
- The barcode creates or resolves the correct part by `rueckmeldenummer`.
- The measuring device produces the four measurement values.
- Measurement is persisted centrally.
- Raw payload is retained for traceability.
- Temporary network interruption does not lose data.
- Supervisor UI shows station health and measurement history.
