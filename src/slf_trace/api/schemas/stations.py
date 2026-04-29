from typing import Any

from pydantic import BaseModel, Field

from slf_trace.api.schemas.companion import MeasurementTypeConfig


class StationBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    hostname: str | None = Field(default=None, max_length=255)
    location: str | None = Field(default=None, max_length=255)
    operating_system: str | None = Field(default=None, max_length=80)
    machine_name: str | None = Field(default=None, max_length=255)
    machine_type: str | None = Field(default=None, max_length=120)
    measurement_interface: str | None = Field(default=None, max_length=80)
    scanner_host: str | None = Field(default=None, max_length=255)
    scanner_port: int | None = Field(default=None, ge=1, le=65535)
    scanner_protocol: str | None = Field(default=None, max_length=80)
    adapter_config: list[dict[str, Any]] = Field(default_factory=list)
    payload_format: str | None = None
    timing_notes: str | None = None
    network_notes: str | None = None
    active: bool = True
    measurement_type_codes: list[str] = Field(default_factory=list)


class StationCreate(StationBase):
    pass


class StationUpdate(BaseModel):
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
    measurement_type_codes: list[str] | None = None


class StationResponse(BaseModel):
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
    measurement_types: list[MeasurementTypeConfig] = Field(default_factory=list)
