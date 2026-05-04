# Station Inventory

Stations are configured centrally and fetched by the companion app during bootstrap.

## Captured Fields

- `name`
- `location`
- `scanner_host`, expected scanner IP address for the TCP listener
- `scanner_port`, local port the companion listens on for scanner connections
- `scanner_protocol`, for example `Keyence SR-X TCP`
- `adapter_config`, the per-station companion adapter definitions
- `payload_format`
- `timing_notes`
- `network_notes`
- `active`
- `measurement_type_codes`, the measurement types this station is allowed to submit

The companion reports its current `hostname` with every heartbeat. Hostname is runtime diagnostics,
not central station configuration.

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

Assigning `measurement_type_codes` replaces the station's active measurement type allowlist.
