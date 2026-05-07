import asyncio
import logging
import platform
import socket
from dataclasses import dataclass, field
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import httpx

from slf_trace import __version__
from slf_trace.companion.adapters.base import (
    AdapterContext,
    BarcodeScanEvent,
    MeasurementAdapter,
    MeasurementEvent,
    RawPayloadEvent,
)
from slf_trace.companion.adapters.factory import (
    build_adapters_from_config,
    build_scanner_adapter_from_station_config,
)
from slf_trace.companion.client import CompanionClient
from slf_trace.companion.outbox import Outbox, OutboxEvent
from slf_trace.config import Settings, get_settings
from slf_trace.parsing import ParserConfig

logger = logging.getLogger(__name__)
CLIENT_FAILURES = (httpx.HTTPError, OSError, ValueError)


@dataclass(frozen=True)
class CompanionRuntimeConfig:
    station_id: int
    server_url: str
    state_path: str
    heartbeat_interval_seconds: float
    outbox_retry_interval_seconds: float
    measurement_aggregation_timeout_seconds: float = 300.0
    station_token: str | None = None


@dataclass
class PendingMeasurementRequest:
    request_id: int
    rueckmeldenummer: str
    expected_measurement_types: set[str]
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    values: dict[str, Any] = field(default_factory=dict)
    source_types: set[str] = field(default_factory=set)
    measured_at: datetime | None = None
    result_status: str = "unknown"


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
        self.client = client or CompanionClient(
            config.server_url,
            station_id=config.station_id,
            station_token=config.station_token,
        )
        self.outbox = outbox or Outbox(config.state_path)
        self.adapters = adapters or []
        self.station_config: dict[str, Any] | None = None
        self.latest_rueckmeldenummer: str | None = None
        self.pending_measurement_request: PendingMeasurementRequest | None = None
        self.last_measurement_request_id = 0

    async def fetch_station_config(self) -> dict[str, Any]:
        self.station_config = await self.client.fetch_station_config(self.config.station_id)
        logger.info(
            "Fetched station config",
            extra={"station_id": self.config.station_id},
        )
        return self.station_config

    def build_heartbeat_payload(self, status: str = "online") -> dict[str, Any]:
        adapter_status: dict[str, Any] = {
            "runtime": status,
            "os": platform.platform(),
            "python": platform.python_version(),
            "outbox_pending": self.outbox.count(),
            "adapters": {
                adapter.name: adapter.health().as_payload() for adapter in self.adapters
            },
        }
        measurement_progress = self.active_measurement_progress_payload()
        if measurement_progress is not None:
            adapter_status["active_measurement_request"] = measurement_progress
        return {
            "station_id": self.config.station_id,
            "status": status,
            "hostname": socket.gethostname(),
            "companion_version": __version__,
            "adapter_status": adapter_status,
        }

    def active_measurement_progress_payload(self) -> dict[str, Any] | None:
        pending = self.pending_measurement_request
        if pending is None:
            return None

        received_values = [
            {
                "measurement_type": value.measurement_type,
                "value": str(value.value),
                "unit": value.unit,
                "result_status": value.result_status,
            }
            for value in sorted(pending.values.values(), key=lambda item: item.measurement_type)
        ]
        return {
            "request_id": pending.request_id,
            "rueckmeldenummer": pending.rueckmeldenummer,
            "expected_measurement_types": sorted(pending.expected_measurement_types),
            "received_measurement_types": sorted(pending.values),
            "missing_measurement_types": sorted(
                pending.expected_measurement_types - pending.values.keys()
            ),
            "values": received_values,
            "started_at": pending.started_at.isoformat(),
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

    def enqueue_barcode_scan_event(self, event: BarcodeScanEvent) -> int:
        return self.enqueue_event("/api/companion/barcode-scans", event.as_payload())

    def enqueue_station_event(
        self,
        *,
        event_type: str,
        severity: str,
        message: str,
        context: dict[str, Any] | None = None,
    ) -> int:
        return self.enqueue_event(
            "/api/companion/events",
            {
                "station_id": self.config.station_id,
                "event_type": event_type,
                "severity": severity,
                "message": message,
                "context": context,
            },
        )

    async def handle_adapter_event(self, event: MeasurementEvent) -> None:
        if event.rueckmeldenummer is not None:
            self.enqueue_measurement_event(event)
            return

        if self.pending_measurement_request is None:
            logger.info(
                "Ignored measurement without barcode",
                extra={"station_id": event.station_id, "source_type": event.source_type},
            )
            return

        self.add_adapter_event_to_pending_request(event)
        if self.pending_request_has_all_expected_values():
            self.submit_pending_measurement(reason="complete")
        else:
            await self.send_progress_heartbeat()

    async def send_progress_heartbeat(self) -> None:
        try:
            await self.send_heartbeat(status="online")
        except CLIENT_FAILURES as exc:
            logger.warning(
                "Progress heartbeat failed",
                extra={"station_id": self.config.station_id, "error": exc.__class__.__name__},
            )

    def add_adapter_event_to_pending_request(self, event: MeasurementEvent) -> None:
        if self.pending_measurement_request is None:
            return

        pending = self.pending_measurement_request
        if not pending.expected_measurement_types:
            pending.expected_measurement_types = {
                value.measurement_type for value in event.values if value.measurement_type
            }

        for value in event.values:
            if value.measurement_type in pending.values:
                logger.info(
                    "Ignored duplicate measurement type for active request",
                    extra={
                        "station_id": event.station_id,
                        "measurement_type": value.measurement_type,
                        "source_type": event.source_type,
                    },
                )
                continue
            pending.values[value.measurement_type] = value

        pending.source_types.add(event.source_type)
        pending.measured_at = max(
            pending.measured_at or event.measured_at,
            event.measured_at,
        )
        if event.result_status != "unknown":
            pending.result_status = event.result_status

    def pending_request_has_all_expected_values(self) -> bool:
        pending = self.pending_measurement_request
        if pending is None or not pending.expected_measurement_types:
            return False
        return pending.expected_measurement_types.issubset(pending.values.keys())

    def submit_pending_measurement(self, *, reason: str) -> None:
        pending = self.pending_measurement_request
        if pending is None:
            return

        if not pending.values:
            self.pending_measurement_request = None
            self.latest_rueckmeldenummer = None
            return

        missing_types = sorted(pending.expected_measurement_types - pending.values.keys())
        if missing_types:
            self.enqueue_station_event(
                event_type="measurement.partial",
                severity="warning",
                message="Measurement request completed with missing adapter values.",
                context={
                    "request_id": pending.request_id,
                    "rueckmeldenummer": pending.rueckmeldenummer,
                    "missing_measurement_types": missing_types,
                    "reason": reason,
                },
            )

        event = MeasurementEvent(
            station_id=self.config.station_id,
            source_type=self.aggregate_source_type(pending.source_types),
            measured_at=pending.measured_at or datetime.now(UTC),
            rueckmeldenummer=pending.rueckmeldenummer,
            idempotency_key=f"measurement_request:{self.config.station_id}:{pending.request_id}",
            result_status=pending.result_status,
            values=list(pending.values.values()),
        )
        self.enqueue_measurement_event(event)
        self.pending_measurement_request = None
        self.latest_rueckmeldenummer = None

    @staticmethod
    def aggregate_source_type(source_types: set[str]) -> str:
        if len(source_types) == 1:
            return next(iter(source_types))
        return "companion_aggregate"

    def pending_request_timed_out(self) -> bool:
        pending = self.pending_measurement_request
        if pending is None or not pending.values:
            return False
        age = datetime.now(UTC) - pending.started_at
        return age.total_seconds() >= self.config.measurement_aggregation_timeout_seconds

    async def handle_raw_payload_event(self, event: RawPayloadEvent) -> None:
        self.enqueue_raw_payload_event(event)

    async def handle_barcode_scan_event(self, event: BarcodeScanEvent) -> None:
        self.enqueue_barcode_scan_event(event)

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
        except CLIENT_FAILURES as exc:
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
        await self.bootstrap_until_ready()
        adapters_ready = self.configure_adapters_safely()
        await self.sync_measurement_request_cursor()
        try:
            await self.send_heartbeat(status="starting" if adapters_ready else "degraded")
        except CLIENT_FAILURES as exc:
            logger.warning(
                "Startup heartbeat failed; companion will keep running",
                extra={
                    "station_id": self.config.station_id,
                    "error": exc.__class__.__name__,
                },
            )

        tasks = [
            asyncio.create_task(self.run_heartbeat_loop()),
            asyncio.create_task(self.run_outbox_loop()),
            asyncio.create_task(self.run_measurement_request_loop()),
            asyncio.create_task(self.run_adapters()),
        ]
        try:
            await asyncio.gather(*tasks)
        finally:
            await self.stop_adapters()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def bootstrap_until_ready(self) -> None:
        while True:
            try:
                await self.fetch_station_config()
                return
            except CLIENT_FAILURES as exc:
                logger.warning(
                    "Station config fetch failed; companion will retry",
                    extra={
                        "station_id": self.config.station_id,
                        "error": exc.__class__.__name__,
                    },
                )
                await asyncio.sleep(self.config.heartbeat_interval_seconds)

    def configure_adapters_safely(self) -> bool:
        try:
            self.configure_adapters_from_station_config()
        except Exception as exc:  # noqa: BLE001 - config/env errors should not restart companion.
            logger.exception(
                "Adapter configuration failed; companion will keep running degraded",
                extra={
                    "station_id": self.config.station_id,
                    "error": exc.__class__.__name__,
                },
            )
            self.adapters = []
            self.enqueue_station_event(
                event_type="adapter.configuration_failed",
                severity="error",
                message="Adapter configuration failed; companion is running without adapters.",
                context={"error": exc.__class__.__name__, "message": str(exc)},
            )
            return False
        return True

    async def stop_adapters(self) -> None:
        await asyncio.gather(
            *(adapter.stop() for adapter in self.adapters),
            return_exceptions=True,
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
            emit_barcode_scan=self.handle_barcode_scan_event,
            measurement_needed=self.measurement_needed,
            measurement_type_needed=self.measurement_type_needed,
        )
        await asyncio.gather(
            *(self.run_adapter_supervisor(adapter, context) for adapter in self.adapters)
        )

    async def run_adapter_supervisor(
        self,
        adapter: MeasurementAdapter,
        context: AdapterContext,
    ) -> None:
        while True:
            try:
                await adapter.start(context)
                if not adapter.restart_on_exit:
                    logger.info(
                        "Adapter completed and will remain stopped",
                        extra={"station_id": self.config.station_id, "adapter": adapter.name},
                    )
                    await asyncio.Future()
                logger.warning(
                    "Adapter stopped unexpectedly; companion will restart it",
                    extra={"station_id": self.config.station_id, "adapter": adapter.name},
                )
                self.enqueue_station_event(
                    event_type="adapter.stopped",
                    severity="warning",
                    message="Adapter stopped unexpectedly and will be restarted.",
                    context={"adapter": adapter.name},
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - adapter libraries raise mixed errors.
                logger.exception(
                    "Adapter crashed; companion will restart it",
                    extra={
                        "station_id": self.config.station_id,
                        "adapter": adapter.name,
                        "error": exc.__class__.__name__,
                    },
                )
                self.enqueue_station_event(
                    event_type="adapter.failure",
                    severity="error",
                    message="Adapter crashed and will be restarted.",
                    context={"adapter": adapter.name, "error": exc.__class__.__name__},
                )
            await asyncio.sleep(self.config.outbox_retry_interval_seconds)

    async def run_heartbeat_loop(self) -> None:
        while True:
            try:
                await self.send_heartbeat(status="online")
            except CLIENT_FAILURES as exc:
                logger.warning(
                    "Heartbeat failed; companion will keep running",
                    extra={
                        "station_id": self.config.station_id,
                        "error": exc.__class__.__name__,
                    },
                )
            await asyncio.sleep(self.config.heartbeat_interval_seconds)

    async def run_outbox_loop(self) -> None:
        while True:
            try:
                await self.flush_outbox_once()
            except Exception as exc:  # noqa: BLE001 - local state errors should not stop runtime.
                logger.exception(
                    "Outbox flush failed; companion will keep running",
                    extra={
                        "station_id": self.config.station_id,
                        "error": exc.__class__.__name__,
                    },
                )
            await asyncio.sleep(self.config.outbox_retry_interval_seconds)

    async def run_measurement_request_loop(self) -> None:
        while True:
            try:
                await self.fetch_measurement_request_once()
                if self.pending_request_timed_out():
                    self.submit_pending_measurement(reason="timeout")
            except Exception as exc:  # noqa: BLE001 - polling loop is a process safety boundary.
                logger.exception(
                    "Measurement request loop failed; companion will keep running",
                    extra={
                        "station_id": self.config.station_id,
                        "error": exc.__class__.__name__,
                    },
                )
            await asyncio.sleep(0.5)

    async def sync_measurement_request_cursor(self, *, max_requests: int = 1000) -> None:
        for _ in range(max_requests):
            try:
                request = await self.client.fetch_measurement_request(
                    self.config.station_id,
                    self.last_measurement_request_id,
                )
            except CLIENT_FAILURES as exc:
                logger.warning(
                    "Measurement request cursor sync failed; companion will continue",
                    extra={
                        "station_id": self.config.station_id,
                        "request_id": self.last_measurement_request_id,
                        "error": exc.__class__.__name__,
                    },
                )
                return
            request_id = request.get("request_id")
            if request_id is None:
                return
            self.last_measurement_request_id = int(request_id)
        logger.warning(
            "Stopped measurement request cursor sync at limit",
            extra={
                "station_id": self.config.station_id,
                "request_id": self.last_measurement_request_id,
            },
        )

    async def fetch_measurement_request_once(self) -> bool:
        try:
            request = await self.client.fetch_measurement_request(
                self.config.station_id,
                self.last_measurement_request_id,
            )
        except CLIENT_FAILURES as exc:
            logger.warning(
                "Measurement request poll failed; companion will keep running",
                extra={
                    "station_id": self.config.station_id,
                    "request_id": self.last_measurement_request_id,
                    "error": exc.__class__.__name__,
                },
            )
            return False
        request_id = request.get("request_id")
        if request_id is None:
            return False

        self.last_measurement_request_id = int(request_id)
        rueckmeldenummer = str(request.get("rueckmeldenummer") or "").strip()
        if not rueckmeldenummer:
            return False

        if self.pending_measurement_request is not None:
            self.submit_pending_measurement(reason="replaced")

        self.pending_measurement_request = PendingMeasurementRequest(
            request_id=self.last_measurement_request_id,
            rueckmeldenummer=rueckmeldenummer,
            expected_measurement_types=self.expected_measurement_types(),
        )
        self.latest_rueckmeldenummer = rueckmeldenummer
        logger.info(
            "Accepted measurement request",
            extra={
                "station_id": self.config.station_id,
                "request_id": self.last_measurement_request_id,
            },
        )
        return True

    def measurement_needed(self) -> bool:
        return self.pending_measurement_request is not None

    def measurement_type_needed(self, measurement_type: str | None) -> bool:
        pending = self.pending_measurement_request
        if pending is None:
            return False
        if not measurement_type:
            return True
        if not pending.expected_measurement_types:
            return True
        return measurement_type not in pending.values

    def expected_measurement_types(self) -> set[str]:
        adapter_measurement_types = self.enabled_adapter_measurement_types()
        if adapter_measurement_types:
            return adapter_measurement_types

        configured_types = (self.station_config or {}).get("measurement_types", [])
        return {
            str(measurement_type["code"])
            for measurement_type in configured_types
            if measurement_type.get("code")
        }

    def enabled_adapter_measurement_types(self) -> set[str]:
        adapter_configs = (self.station_config or {}).get("adapters", [])
        return {
            measurement_type
            for adapter_config in adapter_configs
            if adapter_config.get("enabled", True) is not False
            for measurement_type in [str(adapter_config.get("measurement_type") or "").strip()]
            if measurement_type
        }

    def _parser_config_from_station_config(self) -> ParserConfig:
        measurement_types = self.expected_measurement_types()
        if not measurement_types:
            logger.warning(
                "Station config has no measurement types; adapter parsing will reject values."
            )
        return ParserConfig(measurement_types=measurement_types)

    def configure_adapters_from_station_config(self) -> None:
        if not self.adapters:
            adapter_configs = (self.station_config or {}).get("adapters", [])
            self.adapters = build_adapters_from_config(adapter_configs)
        scanner_adapter = build_scanner_adapter_from_station_config(self.station_config or {})
        if scanner_adapter is not None and all(
            adapter.name != scanner_adapter.name for adapter in self.adapters
        ):
            self.adapters.append(scanner_adapter)


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
        measurement_aggregation_timeout_seconds=(
            settings.companion_measurement_aggregation_timeout_seconds
        ),
        station_token=settings.station_token,
    )


def configure_logging(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    handlers: list[logging.Handler] = [logging.StreamHandler()]

    if settings.companion_log_path:
        log_path = Path(settings.companion_log_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(
            RotatingFileHandler(
                log_path,
                maxBytes=settings.companion_log_max_bytes,
                backupCount=settings.companion_log_backup_count,
                encoding="utf-8",
            )
        )

    for handler in handlers:
        handler.setFormatter(formatter)

    logging.basicConfig(level=logging.INFO, handlers=handlers, force=True)
