
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
            "encoding": "utf-8",
            "reconnect_delay_seconds": 1.5,
        }
    )

    assert config.host == "10.0.0.60"
    assert config.port == 9100
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
        def __init__(self) -> None:
            self.commands = []

        def get_extra_info(self, key):
            if key == "peername":
                return ("10.0.0.21", 12345)
            return None

        def write(self, payload):
            self.commands.append(payload)

        async def drain(self):
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
    assert writer.commands == [b"LON\r", b"LOFF\r"]


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
