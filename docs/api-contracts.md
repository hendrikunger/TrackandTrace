# Companion API Contracts

Base path: `/api/companion`

## Station Config

`GET /stations/{station_id}/config`

Returns the station bootstrap/config view used by the companion app.
The response includes `measurement_types`, which is the list of active measurement types this
station is allowed to submit.
The response also includes `adapters`, which is the per-station companion adapter configuration.
For SMB1 stations this is where fields such as `remote_dir`, `share`, `measurement_type`, and
`value_column_index` are configured.
Scanner fields are also returned here: `scanner_host` is the expected scanner IP address,
`scanner_port` is the local listener port, and `scanner_protocol` is the scanner label.
Station inventory is managed through `/api/stations`; see `docs/station-inventory.md`.

## Heartbeat

`POST /heartbeats`

```json
{
  "station_id": 1,
  "status": "online",
  "companion_version": "dev",
  "adapter_status": {
    "simulator": "online"
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
- `station_measurement_types` defines which active types a station may submit.

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
  adapter state, station config fields, and assigned measurement types.
- `GET /api/stations/{station_id}` returns the same detail for one station.
- `PATCH /api/stations/{station_id}/config` updates centrally managed station configuration.
- `PUT /api/stations/{station_id}/measurement-types` replaces the active measurement type
  assignment for one station.
- `GET /api/measurement-types` returns the controlled measurement type catalog.
- `GET /api/parts/{rueckmeldenummer}/measurements` returns measurement history for one part.
  Pass `station_id` as an optional query parameter to narrow the history to one station.
- `GET /api/raw-payloads/{raw_payload_id}` returns the retained raw payload for parser/device
  debugging.
