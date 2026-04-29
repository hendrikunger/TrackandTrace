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


class StationSummary(BaseModel):
    id: int
    name: str
    hostname: str | None = None
    location: str | None = None
    operating_system: str | None = None
    machine_name: str | None = None
    machine_type: str | None = None
    measurement_interface: str | None = None
    scanner_host: str | None = None
    scanner_port: int | None = None
    scanner_protocol: str | None = None
    adapter_config: list[dict[str, Any]] = Field(default_factory=list)
    payload_format: str | None = None
    timing_notes: str | None = None
    network_notes: str | None = None
    active: bool
    status: str | None = None
    online: bool
    last_heartbeat_at: datetime | None = None
    companion_version: str | None = None
    adapter_status: dict[str, Any] | None = None
    measurement_types: list[StationMeasurementTypeAssignment] = Field(default_factory=list)


class StationConfigUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    hostname: str | None = Field(default=None, max_length=255)
    location: str | None = Field(default=None, max_length=255)
    operating_system: str | None = Field(default=None, max_length=80)
    machine_name: str | None = Field(default=None, max_length=255)
    machine_type: str | None = Field(default=None, max_length=120)
    measurement_interface: str | None = Field(default=None, max_length=80)
    scanner_host: str | None = Field(default=None, max_length=255)
    scanner_port: int | None = Field(default=None, ge=1, le=65535)
    scanner_protocol: str | None = Field(default=None, max_length=80)
    adapter_config: list[dict[str, Any]] | None = None
    payload_format: str | None = None
    timing_notes: str | None = None
    network_notes: str | None = None
    active: bool | None = None


class StationMeasurementTypeUpdate(BaseModel):
    measurement_type_codes: list[str] = Field(default_factory=list)


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
