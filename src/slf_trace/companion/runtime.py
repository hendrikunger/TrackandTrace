import asyncio
import logging
import platform
from dataclasses import dataclass
from typing import Any

import httpx

from slf_trace import __version__
from slf_trace.companion.adapters.base import (
    AdapterContext,
    MeasurementAdapter,
    MeasurementEvent,
    RawPayloadEvent,
)
from slf_trace.companion.adapters.factory import build_adapters_from_config
from slf_trace.companion.client import CompanionClient
from slf_trace.companion.outbox import Outbox, OutboxEvent
from slf_trace.config import Settings, get_settings
from slf_trace.parsing import ParserConfig

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CompanionRuntimeConfig:
    station_id: int
    server_url: str
    state_path: str
    heartbeat_interval_seconds: float
    outbox_retry_interval_seconds: float


class CompanionRuntime:
    def __init__(
        self,
        config: CompanionRuntimeConfig,
        *,
        client: CompanionClient | None = None,
        outbox: Outbox | None = None,
        adapters: list[MeasurementAdapter] | None = None,
    ) -> None:
        self.config = config
        self.client = client or CompanionClient(config.server_url)
        self.outbox = outbox or Outbox(config.state_path)
        self.adapters = adapters or []
        self.station_config: dict[str, Any] | None = None

    async def fetch_station_config(self) -> dict[str, Any]:
        self.station_config = await self.client.fetch_station_config(self.config.station_id)
        logger.info(
            "Fetched station config",
            extra={"station_id": self.config.station_id},
        )
        return self.station_config

    def build_heartbeat_payload(self, status: str = "online") -> dict[str, Any]:
        return {
            "station_id": self.config.station_id,
            "status": status,
            "companion_version": __version__,
            "adapter_status": {
                "runtime": status,
                "os": platform.platform(),
                "python": platform.python_version(),
                "outbox_pending": self.outbox.count(),
                "adapters": {
                    adapter.name: adapter.health().as_payload() for adapter in self.adapters
                },
            },
        }

    async def send_heartbeat(self, status: str = "online") -> dict[str, Any]:
        payload = self.build_heartbeat_payload(status)
        response = await self.client.post_heartbeat(payload)
        logger.info(
            "Sent heartbeat",
            extra={"station_id": self.config.station_id, "status": status},
        )
        return response

    def enqueue_event(self, endpoint: str, payload: dict[str, Any]) -> int:
        event_id = self.outbox.enqueue(endpoint, payload)
        logger.info(
            "Queued outbox event",
            extra={"event_id": event_id, "endpoint": endpoint},
        )
        return event_id

    def enqueue_measurement_event(self, event: MeasurementEvent) -> int:
        return self.enqueue_event("/api/companion/measurements", event.as_payload())

    def enqueue_raw_payload_event(self, event: RawPayloadEvent) -> int:
        return self.enqueue_event("/api/companion/raw-payloads", event.as_payload())

    async def handle_adapter_event(self, event: MeasurementEvent) -> None:
        self.enqueue_measurement_event(event)

    async def handle_raw_payload_event(self, event: RawPayloadEvent) -> None:
        self.enqueue_raw_payload_event(event)

    async def flush_outbox_once(self, limit: int = 50) -> int:
        sent_count = 0
        for event in self.outbox.pending(limit=limit):
            if await self._try_send_outbox_event(event):
                sent_count += 1
        return sent_count

    async def _try_send_outbox_event(self, event: OutboxEvent) -> bool:
        self.outbox.mark_attempt(event.id)
        try:
            await self.client.post_event(event.endpoint, event.payload)
        except (httpx.HTTPError, OSError) as exc:
            logger.warning(
                "Outbox event send failed",
                extra={
                    "event_id": event.id,
                    "endpoint": event.endpoint,
                    "error": exc.__class__.__name__,
                },
            )
            return False

        self.outbox.delete(event.id)
        logger.info(
            "Sent outbox event",
            extra={"event_id": event.id, "endpoint": event.endpoint},
        )
        return True

    async def run_forever(self) -> None:
        await self.fetch_station_config()
        self.configure_adapters_from_station_config()
        await self.send_heartbeat(status="starting")

        await asyncio.gather(
            self.run_heartbeat_loop(),
            self.run_outbox_loop(),
            self.run_adapters(),
        )

    async def run_adapters(self) -> None:
        if not self.adapters:
            await asyncio.Future()

        parser_config = self._parser_config_from_station_config()
        context = AdapterContext(
            station_id=self.config.station_id,
            emit=self.handle_adapter_event,
            parser_config=parser_config,
            emit_raw_payload=self.handle_raw_payload_event,
        )
        await asyncio.gather(*(adapter.start(context) for adapter in self.adapters))

    async def run_heartbeat_loop(self) -> None:
        while True:
            await self.send_heartbeat(status="online")
            await asyncio.sleep(self.config.heartbeat_interval_seconds)

    async def run_outbox_loop(self) -> None:
        while True:
            await self.flush_outbox_once()
            await asyncio.sleep(self.config.outbox_retry_interval_seconds)

    def _parser_config_from_station_config(self) -> ParserConfig:
        measurement_types = {
            str(measurement_type["code"])
            for measurement_type in (self.station_config or {}).get("measurement_types", [])
            if measurement_type.get("code")
        }
        if not measurement_types:
            logger.warning(
                "Station config has no measurement types; adapter parsing will reject values."
            )
        return ParserConfig(measurement_types=measurement_types)

    def configure_adapters_from_station_config(self) -> None:
        if self.adapters:
            return
        adapter_configs = (self.station_config or {}).get("adapters", [])
        self.adapters = build_adapters_from_config(adapter_configs)


def config_from_settings(settings: Settings | None = None) -> CompanionRuntimeConfig:
    settings = settings or get_settings()
    if settings.station_id is None or str(settings.station_id).strip() == "":
        raise ValueError("STATION_ID must be set for the station companion.")

    return CompanionRuntimeConfig(
        station_id=int(settings.station_id),
        server_url=settings.server_url,
        state_path=settings.companion_state_path,
        heartbeat_interval_seconds=settings.companion_heartbeat_interval_seconds,
        outbox_retry_interval_seconds=settings.companion_outbox_retry_interval_seconds,
    )


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
