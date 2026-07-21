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

Laser marking stations can use the Keyence scanner fields to trigger file creation from an existing
part. The companion loads the latest stored value per measurement type for the scanned
`rueckmeldenummer` and writes alternating type/value lines in stable measurement type code order:

```json
{
  "workflow_type": "laser_marking",
  "workflow_config": {
    "laser_output": {
      "path": "/mnt/laser-share",
      "filename_template": "{rueckmeldenummer}.txt",
      "encoding": "utf-8"
    }
  }
}
```

`laser_output.path` is for a locally mounted SMB share. Direct SMB writing is also supported with
`laser_output.smb`, using `server`, `share`, `remote_dir`, `username_env`, and `password_env`.

Label printing stations can use the Keyence scanner fields to load an existing part, show the latest
measurement values in the kiosk, render a selected `.prn` template, and print it on the station PC:

```json
{
  "workflow_type": "label_printing",
  "workflow_config": {
    "label_printing": {
      "template_dir": "C:\\SLF\\TrackTrace\\labels",
      "selected_template": "SLF_81x36_.prn",
      "encoding": "cp1252",
      "print_backend": "win32print",
      "printer_name": "Vario III 107/12",
      "tcp_host": "",
      "tcp_port": 9100,
      "require_confirmation": false,
      "replacements": [
        {
          "measurement_type": "breite",
          "search": "BM[15]-283",
          "replace": "BM[15]{{value}}",
          "value_format": "comma",
          "missing_value_behavior": "block"
        }
      ]
    }
  },
  "adapter_config": [
    {
      "type": "label_printer",
      "name": "label-printer",
      "enabled": true
    }
  ],
  "measurement_type_codes": []
}
```

Use `win32print` for Windows label stations. Raw TCP/IP can be configured as a fallback when the
printer exposes a socket interface. Missing replacement values use `block` by default, shown in the
admin UI as `Drucken blockieren`; `warn_allow_print` lets the kiosk operator print anyway with a
blank space for that value.
