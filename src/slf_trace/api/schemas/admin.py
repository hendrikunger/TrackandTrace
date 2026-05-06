from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


class MeasurementTypeSummary(BaseModel):
    code: str
    label: str
    unit: str | None = None
    active: bool


class StationMeasurementTypeAssignment(BaseModel):
    code: str
    label: str
    unit: str | None = None
    active: bool


class StationEventSummary(BaseModel):
    id: int
    station_id: int
    event_type: str
    severity: str
    message: str
    context: dict[str, Any] | None = None
    occurred_at: datetime


class StationSummary(BaseModel):
    id: int
    name: str
    location: str | None = None
    scanner_host: str | None = None
    scanner_port: int | None = None
    scanner_protocol: str | None = None
    workflow_type: str
    workflow_title: str | None = None
    workflow_config: dict[str, Any] = Field(default_factory=dict)
    adapter_config: list[dict[str, Any]] = Field(default_factory=list)
    payload_format: str | None = None
    timing_notes: str | None = None
    network_notes: str | None = None
    active: bool
    status: str | None = None
    health_state: str
    health_message: str | None = None
    online: bool
    last_heartbeat_at: datetime | None = None
    last_event_at: datetime | None = None
    last_event_type: str | None = None
    last_event_severity: str | None = None
    last_event_message: str | None = None
    hostname: str | None = None
    companion_version: str | None = None
    companion_token_configured: bool = False
    adapter_status: dict[str, Any] | None = None
    measurement_types: list[StationMeasurementTypeAssignment] = Field(default_factory=list)


class StationConfigUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    location: str | None = Field(default=None, max_length=255)
    scanner_host: str | None = Field(default=None, max_length=255)
    scanner_port: int | None = Field(default=None, ge=1, le=65535)
    scanner_protocol: str | None = Field(default=None, max_length=80)
    workflow_type: str | None = Field(default=None, max_length=80)
    workflow_title: str | None = Field(default=None, max_length=120)
    workflow_config: dict[str, Any] | None = None
    adapter_config: list[dict[str, Any]] | None = None
    payload_format: str | None = None
    timing_notes: str | None = None
    network_notes: str | None = None
    active: bool | None = None


class StationMeasurementTypeUpdate(BaseModel):
    measurement_type_codes: list[str] = Field(default_factory=list)


class StationTokenResponse(BaseModel):
    station_id: int
    token: str


class MeasurementValueSummary(BaseModel):
    measurement_type: str
    label: str | None = None
    value: Decimal
    unit: str | None = None
    result_status: str | None = None


class MeasurementHistoryItem(BaseModel):
    id: int
    station_id: int
    station_name: str
    measured_at: datetime
    result_status: str
    source_type: str
    raw_payload_id: int | None = None
    values: list[MeasurementValueSummary] = Field(default_factory=list)


class PartMeasurementHistory(BaseModel):
    part_id: int
    rueckmeldenummer: str
    measurements: list[MeasurementHistoryItem] = Field(default_factory=list)


class RawPayloadDetail(BaseModel):
    id: int
    station_id: int
    station_name: str
    source_type: str
    payload_hash: str
    content: str
    received_at: datetime
