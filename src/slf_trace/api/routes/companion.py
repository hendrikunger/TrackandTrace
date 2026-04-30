from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from slf_trace.api.events import publish_event
from slf_trace.api.schemas.companion import (
    BarcodeScanRequest,
    BarcodeScanResponse,
    MeasurementRequest,
    MeasurementResponse,
    MeasurementTypeConfig,
    ParsedMeasurementRequest,
    RawPayloadRequest,
    RawPayloadResponse,
    StationConfigResponse,
    StationHeartbeatRequest,
    StationHeartbeatResponse,
)
from slf_trace.api.services.companion import (
    get_station_measurement_types,
    get_station_or_404,
    parse_and_record_measurement,
    record_barcode_scan,
    record_heartbeat,
    record_measurement,
    record_raw_payload,
)
from slf_trace.db import get_session

router = APIRouter(prefix="/companion", tags=["companion"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("/stations/{station_id}/config", response_model=StationConfigResponse)
async def get_station_config(station_id: int, session: SessionDep) -> StationConfigResponse:
    station = await get_station_or_404(session, station_id)
    measurement_types = await get_station_measurement_types(session, station_id)
    return StationConfigResponse(
        station_id=station.id,
        name=station.name,
        hostname=station.hostname,
        location=station.location,
        machine_name=station.machine_name,
        machine_type=station.machine_type,
        scanner_host=station.scanner_host,
        scanner_port=station.scanner_port,
        scanner_protocol=station.scanner_protocol,
        active=station.active,
        adapters=station.adapter_config or [],
        measurement_types=[
            MeasurementTypeConfig(
                code=measurement_type.code,
                label=measurement_type.label,
                unit=measurement_type.unit,
            )
            for measurement_type in measurement_types
        ],
    )


@router.post("/heartbeats", response_model=StationHeartbeatResponse)
async def post_heartbeat(
    payload: StationHeartbeatRequest,
    session: SessionDep,
) -> StationHeartbeatResponse:
    heartbeat = await record_heartbeat(session, payload)
    await publish_event(
        "station.heartbeat",
        heartbeat.station_id,
        {
            "heartbeat_id": heartbeat.id,
            "status": heartbeat.status,
            "companion_version": heartbeat.companion_version,
            "adapter_status": heartbeat.adapter_status,
        },
    )
    return StationHeartbeatResponse(
        station_id=heartbeat.station_id,
        heartbeat_id=heartbeat.id,
    )


@router.post("/barcode-scans", response_model=BarcodeScanResponse)
async def post_barcode_scan(
    payload: BarcodeScanRequest,
    session: SessionDep,
) -> BarcodeScanResponse:
    part, created = await record_barcode_scan(session, payload)
    await publish_event(
        "barcode.scan",
        payload.station_id,
        {
            "part_id": part.id,
            "rueckmeldenummer": part.rueckmeldenummer,
            "created": created,
            "source_type": payload.source_type,
            "scanned_at": payload.scanned_at.isoformat() if payload.scanned_at else None,
        },
    )
    return BarcodeScanResponse(
        part_id=part.id,
        rueckmeldenummer=part.rueckmeldenummer,
        created=created,
    )


@router.post("/raw-payloads", response_model=RawPayloadResponse)
async def post_raw_payload(
    payload: RawPayloadRequest,
    session: SessionDep,
) -> RawPayloadResponse:
    raw_payload = await record_raw_payload(session, payload)
    await publish_event(
        "raw_payload.received",
        raw_payload.station_id,
        {
            "raw_payload_id": raw_payload.id,
            "source_type": raw_payload.source_type,
            "payload_hash": raw_payload.payload_hash,
        },
    )
    return RawPayloadResponse(
        raw_payload_id=raw_payload.id,
        payload_hash=raw_payload.payload_hash,
    )


@router.post("/measurements", response_model=MeasurementResponse)
async def post_measurement(
    payload: MeasurementRequest,
    session: SessionDep,
) -> MeasurementResponse:
    measurement, duplicate = await record_measurement(session, payload)
    await publish_event(
        "measurement.captured",
        measurement.station_id,
        {
            "measurement_id": measurement.id,
            "part_id": measurement.part_id,
            "duplicate": duplicate,
            "values_count": len(measurement.values),
            "idempotency_key": measurement.idempotency_key,
        },
    )
    return MeasurementResponse(
        measurement_id=measurement.id,
        part_id=measurement.part_id,
        duplicate=duplicate,
        values_count=len(measurement.values),
    )


@router.post("/parsed-measurements", response_model=MeasurementResponse)
async def post_parsed_measurement(
    payload: ParsedMeasurementRequest,
    session: SessionDep,
) -> MeasurementResponse:
    measurement, duplicate = await parse_and_record_measurement(session, payload)
    await publish_event(
        "measurement.captured",
        measurement.station_id,
        {
            "measurement_id": measurement.id,
            "part_id": measurement.part_id,
            "duplicate": duplicate,
            "values_count": len(measurement.values),
            "idempotency_key": measurement.idempotency_key,
            "raw_payload_id": measurement.raw_payload_id,
        },
    )
    return MeasurementResponse(
        measurement_id=measurement.id,
        part_id=measurement.part_id,
        duplicate=duplicate,
        values_count=len(measurement.values),
    )
