from decimal import Decimal

import pytest

from slf_trace.companion.adapters import AdapterContext
from slf_trace.companion.adapters.factory import (
    build_adapters_from_config,
    serial_request_config_from_dict,
)
from slf_trace.companion.adapters.serial import (
    SerialRequestAdapterConfig,
    SerialRequestMeasurementAdapter,
)
from slf_trace.parsing import ParserConfig


class FakeSerialConnection:
    def __init__(self, response: bytes = b"12.34\r\n") -> None:
        self.response = response
        self.writes = []
        self.closed = False

    def write(self, content: bytes) -> None:
        self.writes.append(content)

    def flush(self) -> None:
        return None

    def readline(self) -> bytes:
        return self.response

    def close(self) -> None:
        self.closed = True


class FakeSerialModule:
    connection = FakeSerialConnection()

    @classmethod
    def Serial(cls, *args, **kwargs):
        cls.args = args
        cls.kwargs = kwargs
        return cls.connection


def test_serial_request_config_uses_old_device_defaults() -> None:
    config = serial_request_config_from_dict(
        {
            "type": "serial_request",
            "port": "COM5",
            "measurement_type": "breite",
        }
    )

    assert config.port == "COM5"
    assert config.measurement_type == "breite"
    assert config.command == "?\r"
    assert config.baudrate == 4800
    assert config.bytesize == 7
    assert config.parity == "E"
    assert config.stopbits == 2.0


def test_factory_builds_serial_request_adapter() -> None:
    adapters = build_adapters_from_config(
        [
            {
                "type": "serial_request",
                "port": "COM5",
                "measurement_type": "breite",
            }
        ]
    )

    assert isinstance(adapters[0], SerialRequestMeasurementAdapter)


@pytest.mark.asyncio
async def test_serial_request_adapter_sends_command_and_emits_measurement(monkeypatch) -> None:
    events = []
    FakeSerialModule.connection = FakeSerialConnection(response=b"12,34\r\n")
    adapter = SerialRequestMeasurementAdapter(
        SerialRequestAdapterConfig(
            port="COM5",
            measurement_type="breite",
            command="?\r",
        )
    )

    async def emit(event):
        events.append(event)

    monkeypatch.setattr(
        "slf_trace.companion.adapters.serial._load_serial_module",
        lambda: FakeSerialModule,
    )

    assert await adapter.poll_once(
        AdapterContext(
            station_id=1,
            emit=emit,
            parser_config=ParserConfig(measurement_types={"breite"}),
        )
    )

    assert FakeSerialModule.kwargs == {
        "baudrate": 4800,
        "bytesize": 7,
        "parity": "E",
        "stopbits": 2.0,
        "timeout": 2.0,
    }
    assert FakeSerialModule.connection.writes == [b"?\r"]
    assert FakeSerialModule.connection.closed is True
    assert events[0].source_type == "serial"
    assert events[0].values[0].measurement_type == "breite"
    assert events[0].values[0].value == Decimal("12.34")


def test_serial_request_adapter_rejects_non_numeric_response(monkeypatch) -> None:
    FakeSerialModule.connection = FakeSerialConnection(response=b"ERR\r\n")
    adapter = SerialRequestMeasurementAdapter(
        SerialRequestAdapterConfig(port="COM5", measurement_type="breite")
    )
    monkeypatch.setattr(
        "slf_trace.companion.adapters.serial._load_serial_module",
        lambda: FakeSerialModule,
    )

    with pytest.raises(ValueError, match="not numeric"):
        adapter.read_once()
