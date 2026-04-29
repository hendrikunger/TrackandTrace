# Measurement Adapters

Measurement adapters run inside the station companion process and translate device output into
canonical companion measurement events.

The adapter contract is defined in `src/slf_trace/companion/adapters/base.py`.

## Lifecycle

Every adapter implements:

- `start(context)`: run until the adapter is stopped or cancelled.
- `stop()`: request shutdown.
- `health()`: return an `AdapterStatus` for companion heartbeats.

`AdapterContext` provides:

- `station_id`: the current station.
- `parser_config`: the allowed measurement type catalog assigned to the station.
- `emit(event)`: async callback used to hand normalized measurements to the runtime.

The runtime queues emitted events into the local SQLite outbox and sends them to
`POST /api/companion/measurements`.

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

```python
from slf_trace.companion.adapters.tcp import TcpLineAdapterConfig, TcpLineMeasurementAdapter

adapter = TcpLineMeasurementAdapter(
    TcpLineAdapterConfig(
        host="10.0.0.50",
        port=9000,
        rueckmeldenummer="RM-DEV-1",
    )
)
```

### Serial Line Adapter

`SerialLineMeasurementAdapter` reads line-delimited values from a serial port. It requires the
optional `pyserial` package in the station companion environment:

```bash
python -m pip install pyserial
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

### SMB1 Polling Adapter

`SmbPollingMeasurementAdapter` supports legacy measuring stations that only write CSV files to an
SMB1 share. It is based on the working station behavior:

- `pysmb` with SMB2 disabled.
- `SMBConnection(..., use_ntlm_v2=False, is_direct_tcp=True)` on port 445.
- reconnect when `echo(b"ping")` fails.
- poll `/ExcelAusgabe` and select the highest numbered file matching `_(\d+)\.csv$`.
- decode as `cp1252`, take the last non-empty line, split by `;`, and read a configured column.
- delete through `smbclient --option=client min protocol=NT1` when the server does not support
  reliable `pysmb` deletion.

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
