import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from slf_trace.companion.adapters.base import (
    AdapterContext,
    AdapterState,
    AdapterStatus,
    MeasurementAdapter,
    MeasurementEvent,
    MeasurementEventValue,
    parse_payload_event,
)


@dataclass(frozen=True)
class SerialLineAdapterConfig:
    port: str
    name: str = "serial-line"
    source_type: str = "serial"
    rueckmeldenummer: str | None = None
    baudrate: int = 9600
    timeout_seconds: float = 1.0
    reconnect_delay_seconds: float = 2.0
    encoding: str = "utf-8"


@dataclass(frozen=True)
class SerialRequestAdapterConfig:
    port: str
    measurement_type: str
    name: str = "serial-request"
    source_type: str = "serial"
    rueckmeldenummer: str | None = None
    command: str = "?\r"
    baudrate: int = 4800
    bytesize: int = 7
    parity: str = "E"
    stopbits: float = 2.0
    timeout_seconds: float = 2.0
    poll_interval_seconds: float = 2.0
    encoding: str = "utf-8"


class SerialLineMeasurementAdapter(MeasurementAdapter):
    def __init__(self, config: SerialLineAdapterConfig) -> None:
        self.config = config
        self.name = config.name
        self._stop_event = asyncio.Event()
        self._status = AdapterStatus(name=self.name, state=AdapterState.STOPPED)

    async def start(self, context: AdapterContext) -> None:
        self._stop_event.clear()
        self._status = AdapterStatus(name=self.name, state=AdapterState.STARTING)

        while not self._stop_event.is_set():
            try:
                await self._run_connection(context)
            except (OSError, UnicodeDecodeError, ValueError, RuntimeError) as exc:
                self._status = AdapterStatus(
                    name=self.name,
                    state=AdapterState.DEGRADED,
                    last_error=str(exc),
                )
                await self._sleep_until_retry()

        self._status = AdapterStatus(name=self.name, state=AdapterState.STOPPED)

    async def stop(self) -> None:
        self._stop_event.set()

    def health(self) -> AdapterStatus:
        return self._status

    async def _run_connection(self, context: AdapterContext) -> None:
        serial_module = _load_serial_module()
        connection = serial_module.Serial(
            self.config.port,
            baudrate=self.config.baudrate,
            timeout=self.config.timeout_seconds,
        )
        self._status = AdapterStatus(name=self.name, state=AdapterState.ONLINE)

        try:
            while not self._stop_event.is_set():
                line = await asyncio.to_thread(connection.readline)
                if not line:
                    continue

                content = line.decode(self.config.encoding).strip()
                if not content:
                    continue

                event = parse_payload_event(
                    station_id=context.station_id,
                    source_type=self.config.source_type,
                    content=content,
                    parser_config=context.parser_config,
                    rueckmeldenummer=self.config.rueckmeldenummer,
                )
                await context.emit(event)
                self._status = AdapterStatus(
                    name=self.name,
                    state=AdapterState.ONLINE,
                    last_event_at=datetime.now(UTC),
                )
        finally:
            connection.close()

    async def _sleep_until_retry(self) -> None:
        try:
            await asyncio.wait_for(
                self._stop_event.wait(),
                timeout=self.config.reconnect_delay_seconds,
            )
        except TimeoutError:
            return


class SerialRequestMeasurementAdapter(MeasurementAdapter):
    def __init__(self, config: SerialRequestAdapterConfig) -> None:
        self.config = config
        self.name = config.name
        self._stop_event = asyncio.Event()
        self._status = AdapterStatus(name=self.name, state=AdapterState.STOPPED)

    async def start(self, context: AdapterContext) -> None:
        self._stop_event.clear()
        self._status = AdapterStatus(name=self.name, state=AdapterState.STARTING)

        while not self._stop_event.is_set():
            try:
                if not _measurement_needed(context, self.config.measurement_type):
                    self._status = AdapterStatus(
                        name=self.name,
                        state=AdapterState.ONLINE,
                        message="Waiting for measurement request",
                        last_event_at=self._status.last_event_at,
                    )
                    await self._sleep_until_poll()
                    continue
                value = await asyncio.to_thread(self.read_once)
                emitted = await self.emit_measurement(context, value)
                self._status = AdapterStatus(
                    name=self.name,
                    state=AdapterState.ONLINE,
                    message="Measurement emitted" if emitted else "No serial response",
                    last_event_at=datetime.now(UTC) if emitted else self._status.last_event_at,
                )
            except Exception as exc:  # noqa: BLE001 - pyserial/termios raise mixed errors.
                self._status = AdapterStatus(
                    name=self.name,
                    state=AdapterState.DEGRADED,
                    last_error=str(exc),
                )

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self.config.poll_interval_seconds,
                )
            except TimeoutError:
                continue

        self._status = AdapterStatus(name=self.name, state=AdapterState.STOPPED)

    async def stop(self) -> None:
        self._stop_event.set()

    def health(self) -> AdapterStatus:
        return self._status

    async def _sleep_until_poll(self) -> None:
        try:
            await asyncio.wait_for(
                self._stop_event.wait(),
                timeout=self.config.poll_interval_seconds,
            )
        except TimeoutError:
            return

    async def poll_once(self, context: AdapterContext) -> bool:
        if self.config.measurement_type not in context.parser_config.measurement_types:
            raise ValueError(
                f"Unsupported measurement type for station: {self.config.measurement_type}."
            )

        return await self.emit_measurement(context, self.read_once())

    async def emit_measurement(self, context: AdapterContext, value: Decimal) -> bool:
        event = MeasurementEvent(
            station_id=context.station_id,
            source_type=self.config.source_type,
            measured_at=datetime.now(UTC),
            rueckmeldenummer=self.config.rueckmeldenummer,
            values=[
                MeasurementEventValue(
                    measurement_type=self.config.measurement_type,
                    value=value,
                    unit=context.parser_config.default_unit,
                )
            ],
        )
        await context.emit(event)
        return True

    def read_once(self) -> Decimal:
        serial_module = _load_serial_module()
        connection = serial_module.Serial(
            self.config.port,
            baudrate=self.config.baudrate,
            bytesize=self.config.bytesize,
            parity=self.config.parity,
            stopbits=self.config.stopbits,
            timeout=self.config.timeout_seconds,
        )
        try:
            connection.write(self.config.command.encode(self.config.encoding))
            if hasattr(connection, "flush"):
                connection.flush()
            line = connection.readline()
        finally:
            connection.close()

        if not line:
            raise ValueError("Serial device returned no measurement.")

        raw_value = line.decode(self.config.encoding).strip()
        try:
            return Decimal(raw_value.replace(",", "."))
        except InvalidOperation as exc:
            raise ValueError(f"Serial measurement is not numeric: {raw_value!r}.") from exc


def _load_serial_module() -> Any:
    try:
        import serial
    except ImportError as exc:
        raise RuntimeError(
            "Serial adapters require the optional 'pyserial' package to be installed."
        ) from exc
    return serial


def _measurement_needed(context: AdapterContext, measurement_type: str | None) -> bool:
    if context.measurement_type_needed is not None:
        return context.measurement_type_needed(measurement_type)
    return context.measurement_needed is None or context.measurement_needed()
