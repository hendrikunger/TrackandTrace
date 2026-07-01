from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from slf_trace.api.events import publish_event
from slf_trace.api.schemas.companion import (
    BarcodeScanRequest,
    BarcodeScanResponse,
    MeasurementRequest,
    MeasurementRequestCommandResponse,
    MeasurementResponse,
    MeasurementTypeConfig,
    ParsedMeasurementRequest,
    PartMeasurementValuesResponse,
    RawPayloadRequest,
    RawPayloadResponse,
    StationConfigResponse,
    StationEventRequest,
    StationEventResponse,
    StationHeartbeatRequest,
    StationHeartbeatResponse,
)
from slf_trace.api.services.companion import (
    get_next_measurement_request,
    get_part_measurement_values,
    get_station_measurement_types,
    get_station_or_404,
    parse_and_record_measurement,
    record_barcode_scan,
    record_heartbeat,
    record_measurement,
    record_raw_payload,
    record_station_event,
)
from slf_trace.config import get_settings
from slf_trace.db import get_session
from slf_trace.security import verify_station_token

router = APIRouter(prefix="/companion", tags=["companion"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
StationIdHeader = Annotated[int | None, Header(alias="X-Station-ID")]
StationTokenHeader = Annotated[str | None, Header(alias="X-Station-Token")]


async def require_companion_auth(
    session: AsyncSession,
    *,
    request_station_id: int,
    header_station_id: int | None,
    header_token: str | None,
) -> None:
    settings = get_settings()
    if not settings.companion_auth_required:
        return

    if header_station_id != request_station_id or not header_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid station credentials.",
        )

    station = await get_station_or_404(session, request_station_id)
    if not verify_station_token(header_token, station.companion_token_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid station credentials.",
        )


@router.get("/stations/{station_id}/config", response_model=StationConfigResponse)
async def get_station_config(
    station_id: int,
    session: SessionDep,
    x_station_id: StationIdHeader = None,
    x_station_token: StationTokenHeader = None,
) -> StationConfigResponse:
    await require_companion_auth(
        session,
        request_station_id=station_id,
        header_station_id=x_station_id,
        header_token=x_station_token,
    )
    station = await get_station_or_404(session, station_id)
    measurement_types = await get_station_measurement_types(session, station_id)
    return StationConfigResponse(
        station_id=station.id,
        name=station.name,
        location=station.location,
        scanner_host=station.scanner_host,
        scanner_port=station.scanner_port,
        scanner_protocol=station.scanner_protocol,
        workflow_type=station.workflow_type,
        workflow_title=station.workflow_title,
        workflow_config=station.workflow_config or {},
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


@router.get(
    "/stations/{station_id}/measurement-request",
    response_model=MeasurementRequestCommandResponse,
)
async def get_measurement_request(
    station_id: int,
    after_id: int,
    session: SessionDep,
    x_station_id: StationIdHeader = None,
    x_station_token: StationTokenHeader = None,
) -> MeasurementRequestCommandResponse:
    await require_companion_auth(
        session,
        request_station_id=station_id,
        header_station_id=x_station_id,
        header_token=x_station_token,
    )
    request = await get_next_measurement_request(session, station_id, after_id)
    if request is None:
        return MeasurementRequestCommandResponse()
    return MeasurementRequestCommandResponse(
        request_id=request.id,
        rueckmeldenummer=request.content.strip(),
    )


@router.get(
    "/stations/{station_id}/parts/{rueckmeldenummer}/measurement-values",
    response_model=PartMeasurementValuesResponse,
)
async def get_companion_part_measurement_values(
    station_id: int,
    rueckmeldenummer: str,
    session: SessionDep,
    x_station_id: StationIdHeader = None,
    x_station_token: StationTokenHeader = None,
) -> PartMeasurementValuesResponse:
    await require_companion_auth(
        session,
        request_station_id=station_id,
        header_station_id=x_station_id,
        header_token=x_station_token,
    )
    return await get_part_measurement_values(
        session,
        station_id=station_id,
        rueckmeldenummer=rueckmeldenummer,
    )


@router.post("/heartbeats", response_model=StationHeartbeatResponse)
async def post_heartbeat(
    payload: StationHeartbeatRequest,
    session: SessionDep,
    x_station_id: StationIdHeader = None,
    x_station_token: StationTokenHeader = None,
) -> StationHeartbeatResponse:
    await require_companion_auth(
        session,
        request_station_id=payload.station_id,
        header_station_id=x_station_id,
        header_token=x_station_token,
    )
    heartbeat = await record_heartbeat(session, payload)
    await publish_event(
        "station.heartbeat",
        heartbeat.station_id,
        {
            "heartbeat_id": heartbeat.id,
            "status": heartbeat.status,
            "hostname": heartbeat.hostname,
            "companion_version": heartbeat.companion_version,
            "adapter_status": heartbeat.adapter_status,
        },
    )
    return StationHeartbeatResponse(
        station_id=heartbeat.station_id,
        heartbeat_id=heartbeat.id,
    )


@router.post("/events", response_model=StationEventResponse)
async def post_station_event(
    payload: StationEventRequest,
    session: SessionDep,
    x_station_id: StationIdHeader = None,
    x_station_token: StationTokenHeader = None,
) -> StationEventResponse:
    await require_companion_auth(
        session,
        request_station_id=payload.station_id,
        header_station_id=x_station_id,
        header_token=x_station_token,
    )
    event = await record_station_event(session, payload)
    await publish_event(
        "station.event",
        event.station_id,
        {
            "event_id": event.id,
            "event_type": event.event_type,
            "severity": event.severity,
            "message": event.message,
            "occurred_at": event.occurred_at.isoformat(),
        },
    )
    return StationEventResponse(
        station_id=event.station_id,
        event_id=event.id,
    )


@router.post("/barcode-scans", response_model=BarcodeScanResponse)
async def post_barcode_scan(
    payload: BarcodeScanRequest,
    session: SessionDep,
    x_station_id: StationIdHeader = None,
    x_station_token: StationTokenHeader = None,
) -> BarcodeScanResponse:
    await require_companion_auth(
        session,
        request_station_id=payload.station_id,
        header_station_id=x_station_id,
        header_token=x_station_token,
    )
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
    x_station_id: StationIdHeader = None,
    x_station_token: StationTokenHeader = None,
) -> RawPayloadResponse:
    await require_companion_auth(
        session,
        request_station_id=payload.station_id,
        header_station_id=x_station_id,
        header_token=x_station_token,
    )
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
    x_station_id: StationIdHeader = None,
    x_station_token: StationTokenHeader = None,
) -> MeasurementResponse:
    await require_companion_auth(
        session,
        request_station_id=payload.station_id,
        header_station_id=x_station_id,
        header_token=x_station_token,
    )
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
    x_station_id: StationIdHeader = None,
    x_station_token: StationTokenHeader = None,
) -> MeasurementResponse:
    await require_companion_auth(
        session,
        request_station_id=payload.station_id,
        header_station_id=x_station_id,
        header_token=x_station_token,
    )
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
