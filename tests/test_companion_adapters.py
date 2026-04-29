import pytest

from slf_trace.companion.adapters import AdapterContext, AdapterState
from slf_trace.companion.adapters.base import parse_payload_event
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
