# Parser Layer

The parser layer converts retained raw payload content into normalized measurement values.

## Supported Scaffold Formats

Key/value payload:

```text
aussenring=1.1;innenring=2.2;breite=3.3;ueberstand=4.4
```

Newline key/value payload:

```text
breite=7,7
ueberstand=4,4
```

Single-row CSV payload:

```csv
breite,ueberstand
3.3,4.4
```

Decimal comma values are accepted and normalized.

## API

Raw payloads are still uploaded first:

```http
POST /api/companion/raw-payloads
```

Then the server can parse the stored raw payload and create a measurement:

```http
POST /api/companion/parsed-measurements
```

```json
{
  "station_id": 1,
  "raw_payload_id": 1,
  "idempotency_key": "parser-event-001",
  "measured_at": "2026-04-28T11:30:00Z",
  "result_status": "pass",
  "rueckmeldenummer": "DEV-RM-0001"
}
```

The parser uses the station's allowed measurement types as its validation config. Unknown fields,
invalid decimal values, empty payloads, and station/raw-payload mismatches are rejected with `422`.

This first slice is intentionally small. Future parser configurations can add station-specific
field aliases, fixed column positions, file encodings, and tolerances.
