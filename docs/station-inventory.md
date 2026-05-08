# Station Inventory

Stations are configured centrally and fetched by the companion app during bootstrap.

## Captured Fields

- `name`
- `location`
- `scanner_host`, expected scanner IP address for the TCP listener
- `scanner_port`, local port the companion listens on for scanner connections
- `scanner_protocol`, for example `Keyence SR-X TCP`
- `workflow_type`, the UI/process workflow identifier
- `workflow_title`, optional station-specific kiosk display title
- `workflow_config`, optional UI/process behavior settings
- `adapter_config`, the per-station companion adapter definitions
- `payload_format`
- `timing_notes`
- `network_notes`
- `active`
- `measurement_type_codes`, the API allowlist for measurement types when no enabled adapter
  declares a `measurement_type`

The companion reports its current `hostname` with every heartbeat. Hostname is runtime diagnostics,
not central station configuration.

For measurement capture stations, the effective measurement type list is usually derived from the
enabled entries in `adapter_config`. If one or more enabled adapters declare `measurement_type`, the
companion config endpoint and server validation use those adapter codes. The
`station_measurement_types` allowlist remains the fallback/manual API path for stations without
adapter-declared measurement types.

## API

List stations:

```http
GET /api/stations
```

Create a station:

```http
POST /api/stations
```

```json
{
  "name": "BREITE-01",
  "location": "Line 1",
  "scanner_host": "10.0.0.21",
  "scanner_port": 9004,
  "scanner_protocol": "Keyence SR-X TCP",
  "workflow_type": "measurement_capture",
  "workflow_title": "Breite messen",
  "workflow_config": {
    "operator_steps": ["scan", "wait_for_measurement", "complete"]
  },
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
  "payload_format": "CSV: rueckmeldenummer, breite",
  "timing_notes": "Poll result share every 2 seconds.",
  "network_notes": "Requires SMB1 access from Ubuntu companion.",
  "measurement_type_codes": ["breite"]
}
```

Update a station:

```http
PATCH /api/stations/{station_id}
```

Assigning `measurement_type_codes` replaces the station's active fallback measurement type
allowlist. The admin UI generally keeps measurement capture assignments in the enabled adapter
definitions instead.

Generate or rotate a station token:

```http
POST /api/stations/{station_id}/token
```

The response contains the raw `STATION_TOKEN` once. Store it in the station service environment; the
database stores only a token hash.

For non-measurement workflows such as `label_printing` or `laser_marking`, leave
`measurement_type_codes` empty and store UI/process behavior in `workflow_config`. Do not add fake
measurement types just to make the station appear in the kiosk.
