from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from slf_trace.api.schemas.admin import (
    MeasurementHistoryItem,
    MeasurementTypeSummary,
    MeasurementValueSummary,
    PartMeasurementHistory,
    RawPayloadDetail,
    StationConfigUpdate,
    StationMeasurementTypeAssignment,
    StationSummary,
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

STATION_ONLINE_WINDOW = timedelta(minutes=5)
ONLINE_HEARTBEAT_STATUSES = {"online", "starting", "degraded"}


def is_station_online(
    status_value: str | None,
    heartbeat_received_at: datetime | None,
    *,
    now: datetime | None = None,
) -> bool:
    if status_value not in ONLINE_HEARTBEAT_STATUSES or heartbeat_received_at is None:
        return False

    reference_time = now or datetime.now(UTC)
    if heartbeat_received_at.tzinfo is None:
        heartbeat_received_at = heartbeat_received_at.replace(tzinfo=UTC)

    return reference_time - heartbeat_received_at <= STATION_ONLINE_WINDOW


async def list_station_summaries(session: AsyncSession) -> list[StationSummary]:
    latest_heartbeat_at = (
        select(
            StationHeartbeat.station_id,
            func.max(StationHeartbeat.received_at).label("received_at"),
        )
        .group_by(StationHeartbeat.station_id)
        .subquery()
    )

    result = await session.execute(
        select(Station, StationHeartbeat)
        .outerjoin(
            latest_heartbeat_at,
            latest_heartbeat_at.c.station_id == Station.id,
        )
        .outerjoin(
            StationHeartbeat,
            (StationHeartbeat.station_id == Station.id)
            & (StationHeartbeat.received_at == latest_heartbeat_at.c.received_at),
        )
        .options(
            selectinload(Station.measurement_type_links).selectinload(
                StationMeasurementType.measurement_type
            )
        )
        .order_by(Station.name)
    )

    summaries = []
    for station, heartbeat in result.unique().all():
        summaries.append(_station_summary(station, heartbeat))
    return summaries


async def get_station_summary(session: AsyncSession, station_id: int) -> StationSummary:
    result = await session.execute(
        select(Station)
        .options(
            selectinload(Station.measurement_type_links).selectinload(
                StationMeasurementType.measurement_type
            ),
            selectinload(Station.heartbeats),
        )
        .where(Station.id == station_id)
    )
    station = result.scalar_one_or_none()
    if station is None:
        raise _not_found(f"Station {station_id} was not found.")

    latest_heartbeat = max(
        station.heartbeats,
        key=lambda heartbeat: heartbeat.received_at,
        default=None,
    )
    return _station_summary(station, latest_heartbeat)


async def update_station_config(
    session: AsyncSession,
    station_id: int,
    payload: StationConfigUpdate,
) -> StationSummary:
    result = await session.execute(
        select(Station)
        .options(
            selectinload(Station.measurement_type_links).selectinload(
                StationMeasurementType.measurement_type
            ),
            selectinload(Station.heartbeats),
        )
        .where(Station.id == station_id)
    )
    station = result.scalar_one_or_none()
    if station is None:
        raise _not_found(f"Station {station_id} was not found.")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(station, field, value)

    await session.flush()
    latest_heartbeat = max(
        station.heartbeats,
        key=lambda heartbeat: heartbeat.received_at,
        default=None,
    )
    return _station_summary(station, latest_heartbeat)


async def list_measurement_types(session: AsyncSession) -> list[MeasurementTypeSummary]:
    result = await session.execute(select(MeasurementType).order_by(MeasurementType.code))
    return [
        MeasurementTypeSummary(
            code=measurement_type.code,
            label=measurement_type.label,
            unit=measurement_type.unit,
            active=measurement_type.active,
        )
        for measurement_type in result.scalars()
    ]


async def replace_station_measurement_types(
    session: AsyncSession,
    station_id: int,
    measurement_type_codes: list[str],
) -> StationSummary:
    station = await session.get(Station, station_id)
    if station is None:
        raise _not_found(f"Station {station_id} was not found.")

    requested_codes = set(measurement_type_codes)
    existing_types = await _measurement_types_for_codes(session, requested_codes)
    existing_codes = {measurement_type.code for measurement_type in existing_types}
    missing_codes = sorted(requested_codes - existing_codes)
    if missing_codes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "Unknown measurement type code.",
                "measurement_types": missing_codes,
            },
        )

    existing_links_result = await session.execute(
        select(StationMeasurementType).where(StationMeasurementType.station_id == station_id)
    )
    links_by_code = {
        link.measurement_type_code: link for link in existing_links_result.scalars()
    }

    for code, link in links_by_code.items():
        link.active = code in requested_codes

    for code in sorted(requested_codes - links_by_code.keys()):
        session.add(
            StationMeasurementType(
                station_id=station_id,
                measurement_type_code=code,
                active=True,
            )
        )

    await session.flush()
    return await get_station_summary(session, station_id)


async def get_measurement_history(
    session: AsyncSession,
    rueckmeldenummer: str,
    station_id: int | None = None,
) -> PartMeasurementHistory:
    result = await session.execute(
        select(Part).where(Part.rueckmeldenummer == rueckmeldenummer)
    )
    part = result.scalar_one_or_none()
    if part is None:
        raise _not_found(f"Part {rueckmeldenummer} was not found.")

    query = (
        select(Measurement)
        .options(
            selectinload(Measurement.station),
            selectinload(Measurement.values).selectinload(MeasurementValue.type_definition),
        )
        .where(Measurement.part_id == part.id)
    )
    if station_id is not None:
        query = query.where(Measurement.station_id == station_id)

    measurements_result = await session.execute(
        query.order_by(Measurement.measured_at.desc(), Measurement.id.desc())
    )
    measurements = list(measurements_result.scalars())

    return PartMeasurementHistory(
        part_id=part.id,
        rueckmeldenummer=part.rueckmeldenummer,
        measurements=[
            MeasurementHistoryItem(
                id=measurement.id,
                station_id=measurement.station_id,
                station_name=measurement.station.name,
                measured_at=measurement.measured_at,
                result_status=measurement.result_status,
                source_type=measurement.source_type,
                raw_payload_id=measurement.raw_payload_id,
                values=[
                    MeasurementValueSummary(
                        measurement_type=value.measurement_type,
                        label=(
                            value.type_definition.label
                            if value.type_definition is not None
                            else None
                        ),
                        value=value.value,
                        unit=value.unit,
                        result_status=value.result_status,
                    )
                    for value in sorted(
                        measurement.values,
                        key=lambda item: item.measurement_type,
                    )
                ],
            )
            for measurement in measurements
        ],
    )


async def get_raw_payload_detail(
    session: AsyncSession,
    raw_payload_id: int,
) -> RawPayloadDetail:
    result = await session.execute(
        select(RawPayload)
        .options(selectinload(RawPayload.station))
        .where(RawPayload.id == raw_payload_id)
    )
    raw_payload = result.scalar_one_or_none()
    if raw_payload is None:
        raise _not_found(f"Raw payload {raw_payload_id} was not found.")

    return RawPayloadDetail(
        id=raw_payload.id,
        station_id=raw_payload.station_id,
        station_name=raw_payload.station.name,
        source_type=raw_payload.source_type,
        payload_hash=raw_payload.payload_hash,
        content=raw_payload.content,
        received_at=raw_payload.received_at,
    )


def _station_summary(
    station: Station,
    heartbeat: StationHeartbeat | None,
) -> StationSummary:
    last_heartbeat_at = heartbeat.received_at if heartbeat is not None else None
    status_value = heartbeat.status if heartbeat is not None else None
    return StationSummary(
        id=station.id,
        name=station.name,
        hostname=station.hostname,
        location=station.location,
        operating_system=station.operating_system,
        machine_name=station.machine_name,
        machine_type=station.machine_type,
        measurement_interface=station.measurement_interface,
        scanner_host=station.scanner_host,
        scanner_port=station.scanner_port,
        scanner_protocol=station.scanner_protocol,
        adapter_config=station.adapter_config or [],
        payload_format=station.payload_format,
        timing_notes=station.timing_notes,
        network_notes=station.network_notes,
        active=station.active,
        status=status_value,
        online=is_station_online(status_value, last_heartbeat_at),
        last_heartbeat_at=last_heartbeat_at,
        companion_version=heartbeat.companion_version if heartbeat is not None else None,
        adapter_status=heartbeat.adapter_status if heartbeat is not None else None,
        measurement_types=[
            StationMeasurementTypeAssignment(
                code=link.measurement_type.code,
                label=link.measurement_type.label,
                unit=link.measurement_type.unit,
                active=link.active,
            )
            for link in sorted(
                station.measurement_type_links,
                key=lambda item: item.measurement_type_code,
            )
        ],
    )


async def _measurement_types_for_codes(
    session: AsyncSession,
    codes: set[str],
) -> list[MeasurementType]:
    if not codes:
        return []

    result = await session.execute(
        select(MeasurementType).where(MeasurementType.code.in_(codes))
    )
    return list(result.scalars())


def _not_found(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
