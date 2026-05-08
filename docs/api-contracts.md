# Companion API Contracts

Base path: `/api/companion`

## Station Config

`GET /stations/{station_id}/config`

Returns the station bootstrap/config view used by the companion app.
The response includes `measurement_types`, which is the list of active measurement types this
station is allowed to submit.
The response also includes `adapters`, which is the per-station companion adapter configuration.
Workflow fields are returned separately as `workflow_type`, `workflow_title`, and `workflow_config`.
This keeps UI/process behavior out of device adapter configuration.
For SMB1 stations this is where fields such as `remote_dir`, `share`, `measurement_type`, and
`value_column_index` are configured.
Scanner fields are also returned here: `scanner_host` is the expected scanner IP address,
`scanner_port` is the local listener port, and `scanner_protocol` is the scanner label.
Station inventory is managed through `/api/stations`; see `docs/station-inventory.md`.

When `COMPANION_AUTH_REQUIRED=true`, every companion endpoint requires:

```http
X-Station-ID: <station_id>
X-Station-Token: <station-token>
```

The header station id must match the station id in the URL or request body.

## Measurement Request Polling

`GET /stations/{station_id}/measurement-request?after_id=0`

Returns the next barcode-created measurement request after the supplied raw-payload/request id. An
empty response means there is currently no newer request.

```json
{
  "request_id": 42,
  "rueckmeldenummer": "DEV-RM-0001"
}
```

The companion uses this endpoint to open one active collection window. Adapters without their own
`rueckmeldenummer` only read while a request is active.

## Heartbeat

`POST /heartbeats`

```json
{
  "station_id": 1,
  "status": "online",
  "hostname": "station-panel-01",
  "companion_version": "dev",
  "adapter_status": {
    "runtime": "online",
    "workflow_type": "measurement_capture",
    "outbox_pending": 0,
    "adapters": {
      "tcp-test": {
        "state": "online"
      }
    }
  }
}
```

## Station Event

`POST /events`

Stores central diagnostics for station-side failures and support events. Parser failures recorded
by the central API also create station events so the raw payload and reason remain visible without
opening the station panel immediately.

```json
{
  "station_id": 1,
  "event_type": "adapter.connection_failed",
  "severity": "error",
  "message": "Scanner connection failed.",
  "context": {
    "adapter": "keyence-srx-scanner"
  }
}
```

## Barcode Scan

`POST /barcode-scans`

Creates or resolves a part by `rueckmeldenummer`.
If `raw_payload` is provided, the server retains the original scanner payload for traceability.

```json
{
  "station_id": 1,
  "rueckmeldenummer": "DEV-RM-0001",
  "source_type": "keyence_srx",
  "scanned_at": "2026-04-29T15:00:00+02:00",
  "raw_payload": "RM-DEV-0001"
}
```

## Raw Payload Upload

`POST /raw-payloads`

Stores the original scanner, device, or file payload. If `payload_hash` is omitted, the server
computes a SHA-256 hash of `content`.

```json
{
  "station_id": 1,
  "source_type": "simulator",
  "content": "aussenring=1.1;innenring=2.2;breite=3.3;ueberstand=4.4"
}
```

## Measurement Capture

`POST /measurements`

Persists parsed measurement values and links them to a station, part, and optional raw payload.
`idempotency_key` is unique per station, so companion retries do not create duplicate measurements.
Each captured value is represented by `measurement_type` plus `value`, which lets dedicated
stations submit only the value they produce and lets future measurement types be added without
changing the endpoint contract.
The submitted `measurement_type` must exist in the server-side measurement type catalog and be
enabled for the station.

```json
{
  "station_id": 1,
  "idempotency_key": "dev-event-0001",
  "source_type": "simulator",
  "measured_at": "2026-04-28T11:30:00Z",
  "result_status": "pass",
  "rueckmeldenummer": "DEV-RM-0001",
  "raw_payload_id": 1,
  "values": [
    {
      "measurement_type": "breite",
      "value": "3.3",
      "unit": "mm",
      "result_status": "pass"
    }
  ]
}
```

A station that produces multiple values can submit multiple entries in `values`.

## Measurement Type Control

Measurement types are controlled in the database:

- `measurement_types` defines known active types, labels, and default units.
- Enabled adapter `measurement_type` fields define the effective station allowlist when present.
- `station_measurement_types` defines the fallback/manual allowlist for stations without
  adapter-declared measurement types.

The initial catalog contains:

| Code | Label | Unit |
| --- | --- | --- |
| `aussenring` | Außenring | `mm` |
| `innenring` | Innenring | `mm` |
| `breite` | Breite | `mm` |
| `ueberstand` | Überstand | `mm` |

## Supervisor/Admin API

The supervisor/admin UI uses the central database to review station health and trace captured
measurements.

- `GET /api/stations` returns the station list with latest heartbeat, online/offline status,
  health state/message, adapter state, latest diagnostics event, station config fields, and
  assigned measurement types.
- `GET /api/stations/{station_id}` returns the same detail for one station.
- `PATCH /api/stations/{station_id}/config` updates centrally managed station configuration.
- `PUT /api/stations/{station_id}/measurement-types` replaces the active measurement type
  assignment for one station.
- `POST /api/stations/{station_id}/token` generates a new station companion token. The raw token is
  returned once and only the hash is retained centrally.
- `GET /api/stations/{station_id}/events` returns recent station diagnostics events.
- `GET /api/measurement-types` returns the controlled measurement type catalog.
- `GET /api/parts/{rueckmeldenummer}/measurements` returns measurement history for one part.
  Pass `station_id` as an optional query parameter to narrow the history to one station.
- `GET /api/raw-payloads/{raw_payload_id}` returns the retained raw payload for parser/device
  debugging.
