import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

from slf_trace.companion.adapters.base import (
    AdapterContext,
    AdapterState,
    AdapterStatus,
    MeasurementAdapter,
    parse_payload_event,
)


@dataclass(frozen=True)
class TcpLineAdapterConfig:
    host: str
    port: int
    measurement_type: str | None = None
    name: str = "tcp-line"
    source_type: str = "tcp"
    rueckmeldenummer: str | None = None
    command: str | None = None
    poll_interval_seconds: float = 1.0
    reconnect_delay_seconds: float = 2.0
    encoding: str = "utf-8"


class TcpLineMeasurementAdapter(MeasurementAdapter):
    def __init__(self, config: TcpLineAdapterConfig) -> None:
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
            except (OSError, TimeoutError, UnicodeDecodeError, ValueError) as exc:
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
        reader, writer = await asyncio.open_connection(self.config.host, self.config.port)
        self._status = AdapterStatus(name=self.name, state=AdapterState.ONLINE)
        try:
            while not self._stop_event.is_set():
                if self.config.command is not None:
                    if not _measurement_needed(context):
                        await self._sleep_until_poll()
                        continue
                    writer.write(self.config.command.encode(self.config.encoding))
                    await writer.drain()

                line = await reader.readline()
                if not line:
                    raise OSError("TCP connection closed by peer.")

                content = line.decode(self.config.encoding).strip()
                if not content:
                    continue
                if self.config.measurement_type is not None and not _has_measurement_key(content):
                    content = f"{self.config.measurement_type}={content}"

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
                if self.config.command is not None:
                    await self._sleep_until_poll()
        finally:
            writer.close()
            await writer.wait_closed()

    async def _sleep_until_poll(self) -> None:
        try:
            await asyncio.wait_for(
                self._stop_event.wait(),
                timeout=self.config.poll_interval_seconds,
            )
        except TimeoutError:
            return

    async def _sleep_until_retry(self) -> None:
        try:
            await asyncio.wait_for(
                self._stop_event.wait(),
                timeout=self.config.reconnect_delay_seconds,
            )
        except TimeoutError:
            return


def _has_measurement_key(content: str) -> bool:
    return "=" in content or ":" in content or "\n" in content or "," in content


def _measurement_needed(context: AdapterContext) -> bool:
    return context.measurement_needed is None or context.measurement_needed()
