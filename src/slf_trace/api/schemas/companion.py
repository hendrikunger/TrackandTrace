from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class ApiAck(BaseModel):
    status: Literal["accepted"] = "accepted"


class MeasurementTypeConfig(BaseModel):
    code: str
    label: str
    unit: str | None = None


class StationConfigResponse(BaseModel):
    station_id: int
    name: str
    location: str | None = None
    scanner_host: str | None = None
    scanner_port: int | None = None
    scanner_protocol: str | None = None
    active: bool
    adapters: list[dict[str, Any]] = Field(default_factory=list)
    measurement_types: list[MeasurementTypeConfig] = Field(default_factory=list)


class StationHeartbeatRequest(BaseModel):
    station_id: int
    status: Literal["online", "degraded", "offline", "starting"] = "online"
    hostname: str | None = Field(default=None, max_length=255)
    companion_version: str | None = Field(default=None, max_length=80)
    adapter_status: dict[str, Any] | None = None


class StationHeartbeatResponse(ApiAck):
    station_id: int
    heartbeat_id: int


class StationEventRequest(BaseModel):
    station_id: int
    event_type: str = Field(min_length=1, max_length=120)
    severity: Literal["info", "warning", "error", "critical"] = "info"
    message: str = Field(min_length=1)
    context: dict[str, Any] | None = None
    occurred_at: datetime | None = None


class StationEventResponse(ApiAck):
    station_id: int
    event_id: int


class BarcodeScanRequest(BaseModel):
    station_id: int
    rueckmeldenummer: str = Field(min_length=1, max_length=120)
    source_type: str = Field(default="keyence_srx", max_length=80)
    scanned_at: datetime | None = None
    raw_payload: str | None = None


class BarcodeScanResponse(ApiAck):
    part_id: int
    rueckmeldenummer: str
    created: bool


class RawPayloadRequest(BaseModel):
    station_id: int
    source_type: str = Field(max_length=80)
    content: str = Field(min_length=1)
    payload_hash: str | None = Field(default=None, max_length=128)


class RawPayloadResponse(ApiAck):
    raw_payload_id: int
    payload_hash: str


class MeasurementValueRequest(BaseModel):
    measurement_type: str = Field(min_length=1, max_length=80)
    value: Decimal
    unit: str | None = Field(default=None, max_length=40)
    result_status: Literal["pass", "fail", "unknown"] | None = None


class MeasurementRequest(BaseModel):
    station_id: int
    idempotency_key: str = Field(min_length=1, max_length=160)
    source_type: str = Field(max_length=80)
    measured_at: datetime
    result_status: Literal["pass", "fail", "unknown"] = "unknown"
    rueckmeldenummer: str | None = Field(default=None, min_length=1, max_length=120)
    part_id: int | None = None
    raw_payload_id: int | None = None
    values: list[MeasurementValueRequest] = Field(min_length=1)

    @model_validator(mode="after")
    def require_part_reference(self) -> "MeasurementRequest":
        if self.part_id is None and self.rueckmeldenummer is None:
            raise ValueError("Either part_id or rueckmeldenummer is required.")
        return self


class MeasurementResponse(ApiAck):
    measurement_id: int
    part_id: int
    duplicate: bool
    values_count: int


class ParsedMeasurementRequest(BaseModel):
    station_id: int
    raw_payload_id: int
    idempotency_key: str = Field(min_length=1, max_length=160)
    measured_at: datetime
    result_status: Literal["pass", "fail", "unknown"] = "unknown"
    rueckmeldenummer: str | None = Field(default=None, min_length=1, max_length=120)
    part_id: int | None = None
    source_type: str | None = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def require_part_reference(self) -> "ParsedMeasurementRequest":
        if self.part_id is None and self.rueckmeldenummer is None:
            raise ValueError("Either part_id or rueckmeldenummer is required.")
        return self
