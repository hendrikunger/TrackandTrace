import asyncio
from decimal import Decimal

import pytest

from slf_trace.companion.adapters import AdapterContext, AdapterState
from slf_trace.companion.adapters.base import parse_payload_event
from slf_trace.companion.adapters.factory import (
    build_adapters_from_config,
    build_scanner_adapter_from_station_config,
    tcp_line_config_from_dict,
)
from slf_trace.companion.adapters.scanner import (
    TcpBarcodeScannerAdapter,
    TcpBarcodeScannerAdapterConfig,
    _extract_scanner_frames,
)
from slf_trace.companion.adapters.simulator import (
    SimulatorAdapterConfig,
    SimulatorMeasurementAdapter,
)
from slf_trace.companion.adapters.smb import (
    SmbPollingAdapterConfig,
    SmbPollingMeasurementAdapter,
)
from slf_trace.companion.adapters.tcp import TcpLineAdapterConfig, TcpLineMeasurementAdapter
from slf_trace.parsing import ParserConfig


def _parser_config() -> ParserConfig:
    return ParserConfig(measurement_types={"breite", "ueberstand"})


def test_parse_payload_event_normalizes_measurement_values() -> None:
    event = parse_payload_event(
        station_id=1,
        source_type="simulator",
        content="breite=12,4;ueberstand=1.5",
        parser_config=_parser_config(),
        rueckmeldenummer="RM-1",
        idempotency_key="event-1",
    )

    assert event.idempotency_key == "event-1"
    assert event.rueckmeldenummer == "RM-1"
    assert [value.measurement_type for value in event.values] == ["breite", "ueberstand"]
    assert event.as_payload()["values"][0]["value"] == "12.4"


def test_tcp_line_config_from_station_adapter_config() -> None:
    config = tcp_line_config_from_dict(
        {
            "type": "tcp_line",
            "host": "10.0.0.60",
            "port": 9100,
            "measurement_type": "breite",
            "command": "?\\r",
            "poll_interval_seconds": 1.5,
            "encoding": "utf-8",
            "reconnect_delay_seconds": 1.5,
        }
    )

    assert config.host == "10.0.0.60"
    assert config.port == 9100
    assert config.measurement_type == "breite"
    assert config.command == "?\r"
    assert config.poll_interval_seconds == 1.5
    assert config.encoding == "utf-8"
    assert config.reconnect_delay_seconds == 1.5


def test_factory_builds_tcp_line_adapter() -> None:
    adapters = build_adapters_from_config(
        [
            {
                "type": "tcp_line",
                "host": "10.0.0.60",
                "port": 9100,
                "measurement_type": "breite",
            }
        ]
    )

    assert isinstance(adapters[0], TcpLineMeasurementAdapter)


@pytest.mark.asyncio
async def test_tcp_line_adapter_maps_bare_value_to_configured_measurement_type(
    monkeypatch,
) -> None:
    events = []
    adapter = TcpLineMeasurementAdapter(
        TcpLineAdapterConfig(
            host="127.0.0.1",
            port=9000,
            measurement_type="breite",
            reconnect_delay_seconds=0.01,
        )
    )

    class FakeReader:
        async def readline(self):
            return b"7.5\n"

    class FakeWriter:
        def close(self):
            return None

        async def wait_closed(self):
            return None

    async def open_connection(host, port):
        return FakeReader(), FakeWriter()

    async def emit(event):
        events.append(event)
        await adapter.stop()

    monkeypatch.setattr("asyncio.open_connection", open_connection)
    context = AdapterContext(
        station_id=1,
        emit=emit,
        parser_config=_parser_config(),
    )

    await adapter.start(context)

    assert events[0].values[0].measurement_type == "breite"
    assert events[0].values[0].value == Decimal("7.5")


@pytest.mark.asyncio
async def test_tcp_line_adapter_maps_decimal_comma_to_configured_measurement_type(
    monkeypatch,
) -> None:
    events = []
    adapter = TcpLineMeasurementAdapter(
        TcpLineAdapterConfig(
            host="127.0.0.1",
            port=9000,
            measurement_type="innenring",
            reconnect_delay_seconds=0.01,
        )
    )

    class FakeReader:
        async def readline(self):
            return b"32,2\n"

    class FakeWriter:
        def close(self):
            return None

        async def wait_closed(self):
            return None

    async def open_connection(host, port):
        return FakeReader(), FakeWriter()

    async def emit(event):
        events.append(event)
        await adapter.stop()

    monkeypatch.setattr("asyncio.open_connection", open_connection)
    context = AdapterContext(
        station_id=1,
        emit=emit,
        parser_config=ParserConfig(measurement_types={"breite", "innenring"}),
    )

    await adapter.start(context)

    assert events[0].values[0].measurement_type == "innenring"
    assert events[0].values[0].value == Decimal("32.2")


def test_factory_builds_scanner_adapter_from_station_config() -> None:
    adapter = build_scanner_adapter_from_station_config(
        {
            "scanner_host": "10.0.0.21",
            "scanner_port": 9004,
            "scanner_protocol": "Keyence SR-X TCP",
        }
    )

    assert isinstance(adapter, TcpBarcodeScannerAdapter)
    assert adapter.config.allowed_peer_host == "10.0.0.21"
    assert adapter.config.listen_port == 9004
    assert adapter.config.startup_command == "LON"
    assert adapter.config.shutdown_command == "LOFF"
    assert adapter.config.command_host == "10.0.0.21"
    assert adapter.config.command_port == 9004
    assert adapter.config.command_hold_seconds == 2.0
    assert adapter.config.startup_command_attempts == 3
    assert adapter.config.startup_command_retry_seconds == 5.0


@pytest.mark.asyncio
async def test_smb_adapter_keeps_running_when_read_raises_unexpected_exception() -> None:
    adapter = SmbPollingMeasurementAdapter(
        SmbPollingAdapterConfig(
            server="truenas.home.io",
            share="agents",
            username="user",
            password="password",
            measurement_type="breite",
            value_column_index=0,
            poll_interval_seconds=0.01,
        )
    )

    def read_once():
        raise Exception("SMB read failed")

    adapter.read_once = read_once
    context = AdapterContext(
        station_id=1,
        emit=lambda event: None,
        parser_config=ParserConfig(measurement_types={"breite"}),
        measurement_needed=lambda: True,
    )

    task = asyncio.create_task(adapter.start(context))
    await asyncio.sleep(0.03)
    await adapter.stop()
    await asyncio.gather(task, return_exceptions=True)

    assert adapter.health().state is AdapterState.STOPPED


@pytest.mark.asyncio
async def test_tcp_barcode_scanner_adapter_sends_keyence_command(monkeypatch) -> None:
    commands = []
    adapter = TcpBarcodeScannerAdapter(
        TcpBarcodeScannerAdapterConfig(
            allowed_peer_host="10.0.0.21",
            command_timeout_seconds=0.01,
            command_hold_seconds=0.0,
        )
    )

    class FakeWriter:
        def write(self, payload):
            commands.append(payload)

        async def drain(self):
            return None

        def close(self):
            return None

        async def wait_closed(self):
            return None

    async def open_connection(host, port):
        assert host == "10.0.0.21"
        assert port == 9004
        return object(), FakeWriter()

    monkeypatch.setattr("asyncio.open_connection", open_connection)

    await adapter._send_startup_command()
    await adapter._send_shutdown_command()

    assert commands == [b"LON\r\n", b"LOFF\r\n"]


@pytest.mark.asyncio
async def test_tcp_barcode_scanner_adapter_emits_barcode_scan_event() -> None:
    barcode_events = []

    adapter = TcpBarcodeScannerAdapter(
        TcpBarcodeScannerAdapterConfig(
            listen_host="127.0.0.1",
            listen_port=9004,
        )
    )

    async def noop(event):
        return None

    class FakeReader:
        def __init__(self) -> None:
            self.chunks = [b"HB\r\n", b"\nRM-12345\r", b""]

        async def read(self, size):
            return self.chunks.pop(0)

    class FakeWriter:
        def get_extra_info(self, key):
            if key == "peername":
                return ("10.0.0.21", 12345)
            return None

        def close(self):
            return None

        async def wait_closed(self):
            return None

    async def emit_barcode(event):
        barcode_events.append(event)

    context = AdapterContext(
        station_id=1,
        emit=noop,
        parser_config=_parser_config(),
        emit_barcode_scan=emit_barcode,
    )

    writer = FakeWriter()
    await adapter._handle_client(context, FakeReader(), writer)

    assert len(barcode_events) == 1
    assert barcode_events[0].rueckmeldenummer == "RM-12345"
    assert barcode_events[0].raw_payload == "RM-12345"


def test_scanner_frame_parser_accepts_crlf_and_lf_prefix_cr_suffix() -> None:
    frames, remainder = _extract_scanner_frames(b"X002B6ML8N\r\n\nX002B6ML8N\r")

    assert frames == [b"X002B6ML8N", b"X002B6ML8N"]
    assert remainder == b""


@pytest.mark.asyncio
async def test_simulator_adapter_emits_measurement_event() -> None:
    events = []

    async def emit(event):
        events.append(event)

    adapter = SimulatorMeasurementAdapter(
        SimulatorAdapterConfig(payload="breite=10.2", rueckmeldenummer="RM-SIM")
    )
    context = AdapterContext(
        station_id=1,
        emit=emit,
        parser_config=_parser_config(),
    )

    await adapter.start(context)

    assert adapter.health().state == AdapterState.ONLINE
    assert events[0].source_type == "simulator"
    assert events[0].values[0].measurement_type == "breite"


@pytest.mark.asyncio
async def test_tcp_line_adapter_emits_measurement_event(monkeypatch) -> None:
    events = []
    adapter = TcpLineMeasurementAdapter(
        TcpLineAdapterConfig(
            host="127.0.0.1",
            port=9000,
            rueckmeldenummer="RM-TCP",
            reconnect_delay_seconds=0.01,
        )
    )

    class FakeReader:
        async def readline(self):
            return b"breite=7.5\n"

    class FakeWriter:
        def __init__(self):
            self.commands = []

        def write(self, payload):
            self.commands.append(payload)

        async def drain(self):
            return None

        def close(self):
            return None

        async def wait_closed(self):
            return None

    async def open_connection(host, port):
        assert host == "127.0.0.1"
        assert port == 9000
        return FakeReader(), FakeWriter()

    async def emit(event):
        events.append(event)
        await adapter.stop()

    monkeypatch.setattr("asyncio.open_connection", open_connection)
    context = AdapterContext(
        station_id=1,
        emit=emit,
        parser_config=_parser_config(),
    )

    await adapter.start(context)

    assert events[0].source_type == "tcp"
    assert events[0].rueckmeldenummer == "RM-TCP"
    assert events[0].values[0].measurement_type == "breite"


@pytest.mark.asyncio
async def test_tcp_line_adapter_sends_query_command(monkeypatch) -> None:
    events = []
    writer = None
    adapter = TcpLineMeasurementAdapter(
        TcpLineAdapterConfig(
            host="127.0.0.1",
            port=9000,
            command="?\r",
            poll_interval_seconds=0.01,
            reconnect_delay_seconds=0.01,
        )
    )

    class FakeReader:
        async def readline(self):
            return b"breite=7.5\n"

    class FakeWriter:
        def __init__(self):
            self.commands = []

        def write(self, payload):
            self.commands.append(payload)

        async def drain(self):
            return None

        def close(self):
            return None

        async def wait_closed(self):
            return None

    async def open_connection(host, port):
        nonlocal writer
        writer = FakeWriter()
        return FakeReader(), writer

    async def emit(event):
        events.append(event)
        await adapter.stop()

    monkeypatch.setattr("asyncio.open_connection", open_connection)
    context = AdapterContext(
        station_id=1,
        emit=emit,
        parser_config=_parser_config(),
    )

    await adapter.start(context)

    assert writer is not None
    assert writer.commands == [b"?\r"]
    assert events[0].values[0].measurement_type == "breite"


@pytest.mark.asyncio
async def test_tcp_line_adapter_waits_for_measurement_request_before_query(
    monkeypatch,
) -> None:
    events = []
    needed = False
    writer = None
    adapter = TcpLineMeasurementAdapter(
        TcpLineAdapterConfig(
            host="127.0.0.1",
            port=9000,
            command="?\r",
            poll_interval_seconds=0.01,
            reconnect_delay_seconds=0.01,
        )
    )

    class FakeReader:
        async def readline(self):
            return b"breite=7.5\n"

    class FakeWriter:
        def __init__(self):
            self.commands = []

        def write(self, payload):
            self.commands.append(payload)

        async def drain(self):
            return None

        def close(self):
            return None

        async def wait_closed(self):
            return None

    async def open_connection(host, port):
        nonlocal writer
        writer = FakeWriter()
        return FakeReader(), writer

    async def emit(event):
        events.append(event)
        await adapter.stop()

    monkeypatch.setattr("asyncio.open_connection", open_connection)
    context = AdapterContext(
        station_id=1,
        emit=emit,
        parser_config=_parser_config(),
        measurement_needed=lambda: needed,
    )

    task = asyncio.create_task(adapter.start(context))
    await asyncio.sleep(0.03)

    assert writer is not None
    assert writer.commands == []

    needed = True
    await task

    assert writer.commands == [b"?\r"]
    assert events[0].values[0].measurement_type == "breite"


@pytest.mark.asyncio
async def test_tcp_line_adapter_stops_query_when_configured_type_is_complete(
    monkeypatch,
) -> None:
    writer = None
    adapter = TcpLineMeasurementAdapter(
        TcpLineAdapterConfig(
            host="127.0.0.1",
            port=9000,
            measurement_type="innenring",
            command="?\r",
            poll_interval_seconds=0.01,
            reconnect_delay_seconds=0.01,
        )
    )

    class FakeReader:
        async def readline(self):
            await asyncio.sleep(1)
            return b""

    class FakeWriter:
        def __init__(self):
            self.commands = []

        def write(self, payload):
            self.commands.append(payload)

        async def drain(self):
            return None

        def close(self):
            return None

        async def wait_closed(self):
            return None

    async def open_connection(host, port):
        nonlocal writer
        writer = FakeWriter()
        return FakeReader(), writer

    async def emit(event):
        raise AssertionError("No event expected when measurement type is complete.")

    monkeypatch.setattr("asyncio.open_connection", open_connection)
    context = AdapterContext(
        station_id=1,
        emit=emit,
        parser_config=ParserConfig(measurement_types={"breite", "innenring"}),
        measurement_type_needed=lambda measurement_type: measurement_type == "breite",
    )

    task = asyncio.create_task(adapter.start(context))
    await asyncio.sleep(0.03)
    await adapter.stop()
    await task

    assert writer is not None
    assert writer.commands == []
