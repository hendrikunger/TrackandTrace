from typing import Any

from pydantic import BaseModel, Field

from slf_trace.api.schemas.companion import MeasurementTypeConfig


class StationBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    location: str | None = Field(default=None, max_length=255)
    scanner_host: str | None = Field(default=None, max_length=255)
    scanner_port: int | None = Field(default=None, ge=1, le=65535)
    scanner_protocol: str | None = Field(default=None, max_length=80)
    workflow_type: str = Field(default="measurement_capture", max_length=80)
    workflow_title: str | None = Field(default=None, max_length=120)
    workflow_config: dict[str, Any] = Field(default_factory=dict)
    adapter_config: list[dict[str, Any]] = Field(default_factory=list)
    payload_format: str | None = None
    timing_notes: str | None = None
    network_notes: str | None = None
    active: bool = True
    measurement_type_codes: list[str] = Field(default_factory=list)


class StationCreate(StationBase):
    pass


class StationUpdate(BaseModel):
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
    measurement_type_codes: list[str] | None = None


class StationResponse(BaseModel):
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
    companion_token_configured: bool = False
    measurement_types: list[MeasurementTypeConfig] = Field(default_factory=list)
