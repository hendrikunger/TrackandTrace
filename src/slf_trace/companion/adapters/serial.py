import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from slf_trace.companion.adapters.base import (
    AdapterContext,
    AdapterState,
    AdapterStatus,
    MeasurementAdapter,
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


def _load_serial_module() -> Any:
    try:
        import serial
    except ImportError as exc:
        raise RuntimeError(
            "Serial adapters require the optional 'pyserial' package to be installed."
        ) from exc
    return serial
