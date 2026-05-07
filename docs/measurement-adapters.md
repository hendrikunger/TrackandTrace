# Measurement Adapters

Measurement adapters run inside the station companion process and translate device output into
canonical companion measurement events.

The adapter contract is defined in `src/slf_trace/companion/adapters/base.py`.

## Lifecycle

Every adapter implements:

- `start(context)`: run until the adapter is stopped or cancelled.
- `stop()`: request shutdown.
- `health()`: return an `AdapterStatus` for companion heartbeats.

The companion runtime supervises every adapter independently. Expected connection failures should
be handled inside the adapter by setting `AdapterState.DEGRADED` and retrying. Unexpected exceptions
are caught by the runtime supervisor, recorded as `adapter.failure`, and the adapter is started
again. This means a failed SMB read, TCP disconnect, scanner command error, or serial exception
should not restart the whole companion app.

Adapters that intentionally complete once should set `restart_on_exit = False` or expose a
`restart_on_exit` property. The built-in one-shot simulator does this so runtime supervision keeps
the companion alive without repeatedly emitting the same test measurement.

`AdapterContext` provides:

- `station_id`: the current station.
- `parser_config`: the allowed measurement type catalog assigned to the station.
- `emit(event)`: async callback used to hand normalized measurements to the runtime.
- `emit_barcode_scan(event)`: async callback used by barcode scanner adapters.

The runtime queues emitted events into the local SQLite outbox and sends them to
`POST /api/companion/measurements`. When a barcode/measurement request is active, the runtime can
aggregate values from multiple adapters into one measurement. It waits for the station's assigned
measurement types and submits once all values are present, or after the aggregation timeout with a
partial-measurement diagnostic event when at least one value has arrived. If no adapter has emitted
a value yet, the request stays open and polling adapters keep looking for device output.

Barcode scanner adapters use `emit_barcode_scan(...)` and the runtime forwards those events to
`POST /api/companion/barcode-scans`.

## Canonical Event

Adapters emit `MeasurementEvent` objects:

```python
MeasurementEvent(
    station_id=1,
    source_type="tcp",
    measured_at=datetime.now(UTC),
    rueckmeldenummer="RM-123",
    idempotency_key="device-event-123",
    values=[
        MeasurementEventValue(
            measurement_type="breite",
            value=Decimal("12.4"),
            unit="mm",
        )
    ],
)
```

The measurement type must exist in the station's allowed measurement type list. This lets a station
send only `breite`, only `ueberstand`, or any future configured measurement type without changing
the API contract.

## Built-In Adapters

### Simulator

`SimulatorMeasurementAdapter` emits one payload or repeats at a configured interval. It is intended
for local development and automated tests.

```python
from slf_trace.companion.adapters.simulator import SimulatorMeasurementAdapter

adapter = SimulatorMeasurementAdapter.from_payload(
    "breite=12.4",
    rueckmeldenummer="RM-DEV-1",
)
```

### TCP Line Adapter

`TcpLineMeasurementAdapter` connects to a TCP server, reads newline-delimited payloads, parses them,
and emits canonical measurement events. If the connection drops, it marks itself degraded and retries.
The runtime supervisor is an extra guard for failures outside the adapter's expected TCP/read/parse
exceptions.

Station-specific `adapter_config` example:

```json
[
  {
    "type": "tcp_line",
    "enabled": true,
    "name": "tcp-line",
    "host": "10.0.0.50",
    "port": 9000,
    "measurement_type": "breite",
    "encoding": "utf-8",
    "reconnect_delay_seconds": 2.0
  }
]
```

The TCP line payload is parsed by the same parser layer as simulator payloads. For example,
`breite=12.4` is valid when `breite` is assigned to that station.

### Serial Line Adapter

`SerialLineMeasurementAdapter` reads line-delimited values from a serial port. It requires the
optional `pyserial` package in the station companion environment:

```bash
python -m pip install -e ".[serial]"
```

Example:

```python
from slf_trace.companion.adapters.serial import SerialLineAdapterConfig, SerialLineMeasurementAdapter

adapter = SerialLineMeasurementAdapter(
    SerialLineAdapterConfig(
        port="/dev/ttyUSB0",
        baudrate=9600,
        rueckmeldenummer="RM-DEV-1",
    )
)
```

`SerialRequestMeasurementAdapter` supports devices that return one value after a command. The
legacy Breite station behavior is represented by these defaults: COM port, 4800 baud, 7 data bits,
even parity, 2 stop bits, send `?\r`, read one line, parse the line as a decimal value.

Station-specific `adapter_config` example:

```json
[
  {
    "type": "serial_request",
    "enabled": true,
    "name": "breite-serial",
    "port": "COM5",
    "command": "?\\r",
    "measurement_type": "breite",
    "baudrate": 4800,
    "bytesize": 7,
    "parity": "E",
    "stopbits": 2.0,
    "timeout_seconds": 2.0,
    "poll_interval_seconds": 2.0,
    "encoding": "utf-8"
  }
]
```

### Keyence SR-X TCP Barcode Scanner

`TcpBarcodeScannerAdapter` listens for a scanner connection on the station's scanner port and
forwards barcode lines to the companion barcode API. Heartbeat messages are tracked in adapter
health and ignored as scans.

Station-specific fields live on the station record, not in `adapter_config`:

- `scanner_host`: expected scanner IP address, used as a peer filter when set.
- `scanner_port`: local port the companion listens on. The scanner connects to this port.
- `scanner_protocol`: `Keyence SR-X TCP` enables the current TCP scanner adapter; `none`
  disables the main scanner. Older `other` values are tolerated by the backend but are not offered in
  the admin UI because no second scanner implementation exists yet.

The companion automatically builds the scanner listener from these station fields.

When the listener starts, it opens a TCP connection to the scanner command endpoint and sends `LON`
followed by CR/LF to put the scanner into working mode. During adapter shutdown, it sends
`LOFF` followed by CR/LF. By default, commands go to `scanner_host:scanner_port`. These
defaults can be overridden with `scanner_command_host`, `scanner_command_port`,
`scanner_startup_command`, `scanner_shutdown_command`, and `scanner_command_terminator` when a
station-specific scanner command contract differs. The startup command is retried three times by
default, five seconds apart, because the scanner command port can lag behind the station listener
after a reconnect. Override this with `scanner_startup_command_attempts` and
`scanner_startup_command_retry_seconds` if needed. The command socket stays open for two seconds
after the payload is sent because the Keyence command endpoint may ignore commands when the client
disconnects immediately. Override this with `scanner_command_hold_seconds` if needed.

### SMB1 Polling Adapter

`SmbPollingMeasurementAdapter` supports legacy measuring stations that only write CSV files to an
SMB1 share. It is based on the working station behavior:

- `pysmb` with SMB2 disabled.
- `SMBConnection(..., use_ntlm_v2=False, is_direct_tcp=True)` on port 445.
- reconnect when `echo(b"ping")` fails.
- keep the polling loop alive when SMB operations raise connection, parse, delete, or library
  exceptions; adapter health becomes degraded until the next successful poll.
- poll `/ExcelAusgabe` and select the highest numbered file matching `_(\d+)\.csv$`.
- decode as `cp1252`, take the last non-empty line, split by `;`, and read a configured column.
- wait for an active kiosk measurement request before reading a file. This prevents the adapter from
  consuming a measurement before the scanner has supplied the Rückmeldenummer.
- delete the file after a successful upload by default. Some SMB measuring devices append the current
  value to a date-based file; deleting after success keeps the next measurement unambiguous.
- delete through `smbclient --option=client min protocol=NT1` when the server does not support
  reliable `pysmb` deletion.

SMB1 remains the default because it matches the production device. For test shares on newer NAS
systems, set `support_smb2`, `use_ntlm_v2`, and `smbclient_min_protocol` explicitly in the station
adapter configuration.

Install the optional SMB dependency on stations that need it:

```bash
python -m pip install -e ".[smb]"
```

Station-specific example for the `adapter_config` field:

```json
[
  {
    "type": "smb1_polling",
    "enabled": true,
    "server": "10.0.0.50",
    "share": "MEASURE",
    "username_env": "SMB_USER",
    "password_env": "SMB_PASSWORD",
    "remote_dir": "/ExcelAusgabe",
    "filename_pattern": "_(\\d+)\\.csv$",
    "measurement_type": "ueberstand",
    "value_column_index": 13,
    "delete_after_success": true,
    "delete_with_smbclient": true,
    "support_smb2": false,
    "use_ntlm_v2": false,
    "smbclient_min_protocol": "NT1",
    "processed_hashes_path": "state/smb-processed.json"
  }
]
```

The companion receives this list from `/api/companion/stations/{station_id}/config` and creates the
adapter after fetching station config. `remote_dir` is therefore configured per station, not in
source code. Prefer `username_env` and `password_env` so secrets stay in station environment
variables instead of the database or repository. SMB1 stations should stay isolated on the
production network segment because SMB1 is a legacy protocol with weak security properties.

## Payload Format

The current parser accepts key-value and single-row CSV payloads:

```text
breite=12,4;ueberstand=1.5
```

```text
breite,ueberstand
12.4,1.5
```

Decimal commas are normalized when enabled in `ParserConfig`.

## Adding A New Adapter

1. Create a class implementing `MeasurementAdapter`.
2. Keep device-specific connection and reconnect logic inside the adapter.
3. Parse incoming payloads with `parse_payload_event(...)` where possible.
4. Emit `MeasurementEvent` through `AdapterContext.emit`.
5. Return useful `AdapterStatus` values so heartbeat data shows adapter health.
6. Add tests that verify emitted events and reconnect/error behavior.
