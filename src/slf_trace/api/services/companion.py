from hashlib import sha256

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from slf_trace.api.schemas.companion import (
    BarcodeScanRequest,
    MeasurementRequest,
    ParsedMeasurementRequest,
    RawPayloadRequest,
    StationHeartbeatRequest,
)
from slf_trace.models import (
    Measurement,
    MeasurementType,
    MeasurementValue,
    Part,
    RawPayload,
    Station,
    StationHeartbeat,
    StationMeasurementType,
)
from slf_trace.parsing import ParserConfig, PayloadParseError, parse_measurement_payload


async def get_station_or_404(session: AsyncSession, station_id: int) -> Station:
    station = await session.get(Station, station_id)
    if station is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Station {station_id} was not found.",
        )
    return station


async def get_or_create_part(
    session: AsyncSession,
    rueckmeldenummer: str,
) -> tuple[Part, bool]:
    result = await session.execute(
        select(Part).where(Part.rueckmeldenummer == rueckmeldenummer)
    )
    part = result.scalar_one_or_none()
    if part is not None:
        return part, False

    part = Part(rueckmeldenummer=rueckmeldenummer)
    session.add(part)
    await session.flush()
    return part, True


async def record_heartbeat(
    session: AsyncSession,
    payload: StationHeartbeatRequest,
) -> StationHeartbeat:
    await get_station_or_404(session, payload.station_id)
    heartbeat = StationHeartbeat(
        station_id=payload.station_id,
        status=payload.status,
        companion_version=payload.companion_version,
        adapter_status=payload.adapter_status,
    )
    session.add(heartbeat)
    await session.flush()
    return heartbeat


async def record_barcode_scan(
    session: AsyncSession,
    payload: BarcodeScanRequest,
) -> tuple[Part, bool]:
    await get_station_or_404(session, payload.station_id)
    if payload.raw_payload is not None:
        raw_payload = RawPayload(
            station_id=payload.station_id,
            source_type=payload.source_type,
            payload_hash=sha256(payload.raw_payload.encode("utf-8")).hexdigest(),
            content=payload.raw_payload,
        )
        session.add(raw_payload)
    return await get_or_create_part(session, payload.rueckmeldenummer)


async def record_raw_payload(
    session: AsyncSession,
    payload: RawPayloadRequest,
) -> RawPayload:
    await get_station_or_404(session, payload.station_id)
    payload_hash = payload.payload_hash or sha256(payload.content.encode("utf-8")).hexdigest()
    raw_payload = RawPayload(
        station_id=payload.station_id,
        source_type=payload.source_type,
        payload_hash=payload_hash,
        content=payload.content,
    )
    session.add(raw_payload)
    await session.flush()
    return raw_payload


async def record_measurement(
    session: AsyncSession,
    payload: MeasurementRequest,
) -> tuple[Measurement, bool]:
    await get_station_or_404(session, payload.station_id)
    await validate_measurement_types(session, payload)

    existing = await find_measurement_by_idempotency(
        session,
        station_id=payload.station_id,
        idempotency_key=payload.idempotency_key,
    )
    if existing is not None:
        return existing, True

    part = await resolve_measurement_part(session, payload)
    if payload.raw_payload_id is not None:
        await ensure_raw_payload(session, payload.raw_payload_id)

    measurement = Measurement(
        part_id=part.id,
        station_id=payload.station_id,
        result_status=payload.result_status,
        measured_at=payload.measured_at,
        source_type=payload.source_type,
        raw_payload_id=payload.raw_payload_id,
        idempotency_key=payload.idempotency_key,
        values=[
            MeasurementValue(
                measurement_type=value.measurement_type,
                value=value.value,
                unit=value.unit,
                result_status=value.result_status,
            )
            for value in payload.values
        ],
    )
    session.add(measurement)

    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        existing = await find_measurement_by_idempotency(
            session,
            station_id=payload.station_id,
            idempotency_key=payload.idempotency_key,
        )
        if existing is not None:
            return existing, True
        raise

    return measurement, False


async def parse_and_record_measurement(
    session: AsyncSession,
    payload: ParsedMeasurementRequest,
) -> tuple[Measurement, bool]:
    raw_payload = await session.get(RawPayload, payload.raw_payload_id)
    if raw_payload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Raw payload {payload.raw_payload_id} was not found.",
        )
    if raw_payload.station_id != payload.station_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Raw payload station_id does not match request station_id.",
        )

    allowed_types = await get_station_measurement_types(session, payload.station_id)
    config = ParserConfig(
        measurement_types={measurement_type.code for measurement_type in allowed_types},
    )
    try:
        parsed_values = parse_measurement_payload(raw_payload.content, config)
    except PayloadParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": str(exc), "raw_payload_id": payload.raw_payload_id},
        ) from exc

    measurement_payload = MeasurementRequest(
        station_id=payload.station_id,
        idempotency_key=payload.idempotency_key,
        source_type=payload.source_type or raw_payload.source_type,
        measured_at=payload.measured_at,
        result_status=payload.result_status,
        rueckmeldenummer=payload.rueckmeldenummer,
        part_id=payload.part_id,
        raw_payload_id=payload.raw_payload_id,
        values=[
            {
                "measurement_type": value.measurement_type,
                "value": value.value,
                "unit": value.unit,
            }
            for value in parsed_values
        ],
    )
    return await record_measurement(session, measurement_payload)


async def find_measurement_by_idempotency(
    session: AsyncSession,
    *,
    station_id: int,
    idempotency_key: str,
) -> Measurement | None:
    result = await session.execute(
        select(Measurement)
        .options(selectinload(Measurement.values))
        .where(
            Measurement.station_id == station_id,
            Measurement.idempotency_key == idempotency_key,
        )
    )
    return result.scalar_one_or_none()


async def resolve_measurement_part(
    session: AsyncSession,
    payload: MeasurementRequest,
) -> Part:
    if payload.part_id is not None:
        part = await session.get(Part, payload.part_id)
        if part is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Part {payload.part_id} was not found.",
            )
        return part

    assert payload.rueckmeldenummer is not None
    part, _ = await get_or_create_part(session, payload.rueckmeldenummer)
    return part


async def ensure_raw_payload(session: AsyncSession, raw_payload_id: int) -> None:
    raw_payload = await session.get(RawPayload, raw_payload_id)
    if raw_payload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Raw payload {raw_payload_id} was not found.",
        )


async def get_station_measurement_types(
    session: AsyncSession,
    station_id: int,
) -> list[MeasurementType]:
    result = await session.execute(
        select(MeasurementType)
        .join(
            StationMeasurementType,
            StationMeasurementType.measurement_type_code == MeasurementType.code,
        )
        .where(
            StationMeasurementType.station_id == station_id,
            StationMeasurementType.active.is_(True),
            MeasurementType.active.is_(True),
        )
        .order_by(MeasurementType.code)
    )
    return list(result.scalars())


async def validate_measurement_types(
    session: AsyncSession,
    payload: MeasurementRequest,
) -> None:
    allowed_types = await get_station_measurement_types(session, payload.station_id)
    allowed_codes = {measurement_type.code for measurement_type in allowed_types}
    requested_codes = {value.measurement_type for value in payload.values}
    disallowed_codes = sorted(requested_codes - allowed_codes)

    if disallowed_codes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "Measurement type is not active or not allowed for this station.",
                "measurement_types": disallowed_codes,
                "station_id": payload.station_id,
            },
        )
