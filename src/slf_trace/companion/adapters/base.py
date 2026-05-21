import uuid
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from slf_trace.parsing import ParserConfig, parse_measurement_payload


class AdapterState(StrEnum):
    STOPPED = "stopped"
    STARTING = "starting"
    ONLINE = "online"
    DEGRADED = "degraded"
    OFFLINE = "offline"


@dataclass(frozen=True)
class MeasurementEventValue:
    measurement_type: str
    value: Decimal
    unit: str | None = None
    result_status: str | None = None


@dataclass(frozen=True)
class MeasurementEvent:
    station_id: int
    source_type: str
    measured_at: datetime
    rueckmeldenummer: str | None
    values: Sequence[MeasurementEventValue]
    idempotency_key: str = field(default_factory=lambda: uuid.uuid4().hex)
    result_status: str = "unknown"
    part_id: int | None = None
    raw_payload_id: int | None = None
    raw_payload_content: str | None = None

    def as_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "station_id": self.station_id,
            "idempotency_key": self.idempotency_key,
            "source_type": self.source_type,
            "measured_at": self.measured_at.isoformat(),
            "result_status": self.result_status,
            "values": [
                {
                    "measurement_type": value.measurement_type,
                    "value": str(value.value),
                    "unit": value.unit,
                    "result_status": value.result_status,
                }
                for value in self.values
            ],
        }
        if self.rueckmeldenummer is not None:
            payload["rueckmeldenummer"] = self.rueckmeldenummer
        if self.part_id is not None:
            payload["part_id"] = self.part_id
        if self.raw_payload_id is not None:
            payload["raw_payload_id"] = self.raw_payload_id
        return payload


@dataclass(frozen=True)
class RawPayloadEvent:
    station_id: int
    source_type: str
    content: str
    payload_hash: str | None = None

    def as_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "station_id": self.station_id,
            "source_type": self.source_type,
            "content": self.content,
        }
        if self.payload_hash is not None:
            payload["payload_hash"] = self.payload_hash
        return payload


@dataclass(frozen=True)
class BarcodeScanEvent:
    station_id: int
    source_type: str
    rueckmeldenummer: str
    scanned_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    raw_payload: str | None = None

    def as_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "station_id": self.station_id,
            "rueckmeldenummer": self.rueckmeldenummer,
            "source_type": self.source_type,
            "scanned_at": self.scanned_at.isoformat(),
        }
        if self.raw_payload is not None:
            payload["raw_payload"] = self.raw_payload
        return payload


@dataclass(frozen=True)
class AdapterStatus:
    name: str
    state: AdapterState
    message: str | None = None
    last_error: str | None = None
    last_event_at: datetime | None = None

    def as_payload(self) -> dict[str, object]:
        payload = asdict(self)
        payload["state"] = self.state.value
        if self.last_event_at is not None:
            payload["last_event_at"] = self.last_event_at.isoformat()
        return payload


AdapterEmit = Callable[[MeasurementEvent], Awaitable[None]]
RawPayloadEmit = Callable[[RawPayloadEvent], Awaitable[None]]
BarcodeScanEmit = Callable[[BarcodeScanEvent], Awaitable[None]]
StationEventEmit = Callable[
    [str, str, str, dict[str, object] | None],
    Awaitable[None],
]
MeasurementNeeded = Callable[[], bool]
MeasurementTypeNeeded = Callable[[str | None], bool]


@dataclass(frozen=True)
class AdapterContext:
    station_id: int
    emit: AdapterEmit
    parser_config: ParserConfig
    emit_raw_payload: RawPayloadEmit | None = None
    emit_barcode_scan: BarcodeScanEmit | None = None
    emit_station_event: StationEventEmit | None = None
    measurement_needed: MeasurementNeeded | None = None
    measurement_type_needed: MeasurementTypeNeeded | None = None


class MeasurementAdapter(ABC):
    name: str
    restart_on_exit: bool = True

    @abstractmethod
    async def start(self, context: AdapterContext) -> None:
        """Run the adapter until stopped or cancelled."""

    @abstractmethod
    async def stop(self) -> None:
        """Request adapter shutdown."""

    @abstractmethod
    def health(self) -> AdapterStatus:
        """Return current adapter health for companion heartbeats."""


def parse_payload_event(
    *,
    station_id: int,
    source_type: str,
    content: str,
    parser_config: ParserConfig,
    rueckmeldenummer: str | None,
    idempotency_key: str | None = None,
    measured_at: datetime | None = None,
    result_status: str = "unknown",
) -> MeasurementEvent:
    parsed_values = parse_measurement_payload(content, parser_config)
    return MeasurementEvent(
        station_id=station_id,
        source_type=source_type,
        measured_at=measured_at or datetime.now(UTC),
        rueckmeldenummer=rueckmeldenummer,
        idempotency_key=idempotency_key or uuid.uuid4().hex,
        result_status=result_status,
        raw_payload_content=content,
        values=[
            MeasurementEventValue(
                measurement_type=value.measurement_type,
                value=value.value,
                unit=value.unit,
            )
            for value in parsed_values
        ],
    )
