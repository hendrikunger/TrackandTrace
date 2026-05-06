from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from slf_trace.api.schemas.stations import StationCreate, StationResponse, StationUpdate
from slf_trace.models import MeasurementType, Station, StationMeasurementType
from slf_trace.security import generate_station_token, hash_station_token

STATION_MUTABLE_FIELDS = (
    "location",
    "scanner_host",
    "scanner_port",
    "scanner_protocol",
    "workflow_type",
    "workflow_title",
    "workflow_config",
    "adapter_config",
    "payload_format",
    "timing_notes",
    "network_notes",
    "active",
)


async def list_station_inventory(session: AsyncSession) -> list[StationResponse]:
    result = await session.execute(
        select(Station)
        .options(selectinload(Station.measurement_type_links))
        .order_by(Station.name)
    )
    stations = result.scalars().all()
    return [await station_to_response(session, station) for station in stations]


async def create_station_inventory(
    session: AsyncSession,
    payload: StationCreate,
) -> StationResponse:
    existing = await station_by_name(session, payload.name)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Station {payload.name!r} already exists.",
        )

    station = Station(name=payload.name)
    apply_station_fields(station, payload)
    session.add(station)
    await session.flush()
    await replace_station_measurement_types(
        session,
        station,
        payload.measurement_type_codes,
    )
    await session.flush()
    return await station_to_response(session, station)


async def update_station_inventory(
    session: AsyncSession,
    station_id: int,
    payload: StationUpdate,
) -> StationResponse:
    station = await get_station_inventory_or_404(session, station_id)
    values = payload.model_dump(exclude_unset=True)
    for field in STATION_MUTABLE_FIELDS:
        if field in values:
            setattr(station, field, values[field])

    if "measurement_type_codes" in values:
        await replace_station_measurement_types(
            session,
            station,
            values["measurement_type_codes"] or [],
        )

    await session.flush()
    return await station_to_response(session, station)


async def get_station_inventory_or_404(session: AsyncSession, station_id: int) -> Station:
    station = await session.get(Station, station_id)
    if station is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Station {station_id} was not found.",
        )
    return station


async def rotate_station_token(session: AsyncSession, station_id: int) -> str:
    station = await get_station_inventory_or_404(session, station_id)
    token = generate_station_token()
    station.companion_token_hash = hash_station_token(token)
    await session.flush()
    return token


async def station_by_name(session: AsyncSession, name: str) -> Station | None:
    result = await session.execute(select(Station).where(Station.name == name))
    return result.scalar_one_or_none()


def apply_station_fields(station: Station, payload: StationCreate) -> None:
    for field in STATION_MUTABLE_FIELDS:
        setattr(station, field, getattr(payload, field))


async def replace_station_measurement_types(
    session: AsyncSession,
    station: Station,
    measurement_type_codes: list[str],
) -> None:
    codes = list(dict.fromkeys(measurement_type_codes))
    await session.execute(
        delete(StationMeasurementType).where(
            StationMeasurementType.station_id == station.id,
        )
    )
    if not codes:
        return

    result = await session.execute(
        select(MeasurementType).where(
            MeasurementType.code.in_(codes),
            MeasurementType.active.is_(True),
        )
    )
    existing_codes = {measurement_type.code for measurement_type in result.scalars()}
    missing_codes = sorted(set(codes) - existing_codes)
    if missing_codes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "Unknown or inactive measurement type.",
                "measurement_types": missing_codes,
            },
        )

    session.add_all(
        [
            StationMeasurementType(
                station_id=station.id,
                measurement_type_code=code,
                active=True,
            )
            for code in codes
        ]
    )


async def station_to_response(session: AsyncSession, station: Station) -> StationResponse:
    result = await session.execute(
        select(MeasurementType)
        .join(
            StationMeasurementType,
            StationMeasurementType.measurement_type_code == MeasurementType.code,
        )
        .where(
            StationMeasurementType.station_id == station.id,
            StationMeasurementType.active.is_(True),
            MeasurementType.active.is_(True),
        )
        .order_by(MeasurementType.code)
    )
    measurement_types = result.scalars().all()
    return StationResponse(
        id=station.id,
        name=station.name,
        location=station.location,
        scanner_host=station.scanner_host,
        scanner_port=station.scanner_port,
        scanner_protocol=station.scanner_protocol,
        workflow_type=station.workflow_type,
        workflow_title=station.workflow_title,
        workflow_config=station.workflow_config or {},
        adapter_config=station.adapter_config or [],
        payload_format=station.payload_format,
        timing_notes=station.timing_notes,
        network_notes=station.network_notes,
        active=station.active,
        companion_token_configured=bool(station.companion_token_hash),
        measurement_types=[
            {
                "code": measurement_type.code,
                "label": measurement_type.label,
                "unit": measurement_type.unit,
            }
            for measurement_type in measurement_types
        ],
    )
