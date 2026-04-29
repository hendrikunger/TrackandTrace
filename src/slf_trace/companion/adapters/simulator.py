import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Self

from slf_trace.companion.adapters.base import (
    AdapterContext,
    AdapterState,
    AdapterStatus,
    MeasurementAdapter,
    parse_payload_event,
)


@dataclass(frozen=True)
class SimulatorAdapterConfig:
    name: str = "simulator"
    source_type: str = "simulator"
    payload: str = "breite=10.0"
    rueckmeldenummer: str = "SIM-RM-1"
    interval_seconds: float | None = None


class SimulatorMeasurementAdapter(MeasurementAdapter):
    def __init__(self, config: SimulatorAdapterConfig | None = None) -> None:
        self.config = config or SimulatorAdapterConfig()
        self.name = self.config.name
        self._stop_event = asyncio.Event()
        self._status = AdapterStatus(name=self.name, state=AdapterState.STOPPED)

    async def start(self, context: AdapterContext) -> None:
        self._stop_event.clear()
        self._status = AdapterStatus(name=self.name, state=AdapterState.STARTING)

        while not self._stop_event.is_set():
            event = parse_payload_event(
                station_id=context.station_id,
                source_type=self.config.source_type,
                content=self.config.payload,
                parser_config=context.parser_config,
                rueckmeldenummer=self.config.rueckmeldenummer,
            )
            await context.emit(event)
            self._status = AdapterStatus(
                name=self.name,
                state=AdapterState.ONLINE,
                last_event_at=datetime.now(UTC),
            )

            if self.config.interval_seconds is None:
                break
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self.config.interval_seconds,
                )
            except TimeoutError:
                continue

        if self._stop_event.is_set():
            self._status = AdapterStatus(name=self.name, state=AdapterState.STOPPED)

    async def stop(self) -> None:
        self._stop_event.set()

    def health(self) -> AdapterStatus:
        return self._status

    @classmethod
    def from_payload(
        cls,
        payload: str,
        *,
        rueckmeldenummer: str = "SIM-RM-1",
        interval_seconds: float | None = None,
    ) -> Self:
        return cls(
            SimulatorAdapterConfig(
                payload=payload,
                rueckmeldenummer=rueckmeldenummer,
                interval_seconds=interval_seconds,
            )
        )
