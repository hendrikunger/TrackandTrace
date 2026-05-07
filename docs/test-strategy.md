# Test Strategy And Simulators

ABO-23 keeps the normal development loop independent from real measuring devices. Device-specific
adapters still need hardware commissioning, but schema logic, ingest APIs, parsing, retry behavior,
and simulator tooling are covered by automated tests.

## Local Checks

Run these before handing off changes:

```bash
ruff check .
pytest
python -m compileall src tests
```

`pytest` covers:

- Companion schema validation and route registration.
- Barcode scan and measurement API behavior, including duplicate idempotency responses.
- Parser behavior for key-value payloads, decimal commas, CSV payloads, unknown types, and invalid
  values.
- Adapter behavior for simulator, TCP line, Keyence SR-X barcode frames, serial factories, and
  SMB1 polling.
- Companion outbox persistence, retry, API-outage bootstrap safety, measurement-request polling
  outage safety, and adapter supervisor restart behavior.

## Simulators

Install the project in the active environment, then use the `slf-trace-sim` console script.

### Drive The API Directly

This is the fastest way to make the operator UI show a scanned part and a captured measurement:

```bash
slf-trace-sim api \
  --server-url http://localhost:8000 \
  --station-id 1 \
  --rueckmeldenummer RM-DEV-0001 \
  --measurement-type breite \
  --value 12.4
```

The command posts a barcode scan first, then a measurement with a generated idempotency key unless
one is supplied with `--idempotency-key`.

### Simulate A Keyence Barcode Scanner

Run the companion for a station whose scanner listener is enabled, then send a barcode frame:

```bash
slf-trace-sim keyence --host 127.0.0.1 --port 9004 --barcode RM-DEV-0001
```

The simulator writes the same CR/LF-terminated ASCII frame that the Keyence TCP adapter consumes.

### Simulate An SMB/File Payload

Write a numbered CSV file compatible with the SMB1 polling adapter's default behavior:

```bash
slf-trace-sim smb-file \
  --directory /tmp/slf-smb \
  --sequence 10 \
  --value-column-index 13 \
  --value 12.4
```

The file uses CP1252 text, semicolon columns, and decimal commas by default. For a real SMB test,
copy the generated file into the station share directory configured in the admin adapter settings.

## Hardware Boundary

Automated tests verify the protocol and ingest behavior around the hardware boundary. Final machine
commissioning should still confirm:

- The Keyence scanner can connect to the companion listener from the production network segment.
- SMB1 credentials, share path, filename pattern, encoding, and delete-after-success behavior match
  the legacy measuring PC.
- Serial port names and baud/parity/stop-bit settings match the attached device.
