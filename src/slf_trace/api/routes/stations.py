from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from slf_trace.api.schemas.admin import (
    StationConfigUpdate,
    StationEventSummary,
    StationMeasurementTypeUpdate,
    StationSummary,
)
from slf_trace.api.schemas.stations import StationCreate, StationResponse, StationUpdate
from slf_trace.api.services.admin import (
    get_station_summary,
    list_station_events,
    list_station_summaries,
    update_station_config,
)
from slf_trace.api.services.admin import (
    replace_station_measurement_types as replace_admin_station_measurement_types,
)
from slf_trace.api.services.stations import (
    create_station_inventory,
    update_station_inventory,
)
from slf_trace.db import get_session

router = APIRouter(prefix="/stations", tags=["stations"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("", response_model=list[StationSummary])
async def list_stations(session: SessionDep) -> list[StationSummary]:
    return await list_station_summaries(session)


@router.post("", response_model=StationResponse, status_code=201)
async def create_station(
    payload: StationCreate,
    session: SessionDep,
) -> StationResponse:
    return await create_station_inventory(session, payload)


@router.get("/{station_id}", response_model=StationSummary)
async def get_station(station_id: int, session: SessionDep) -> StationSummary:
    return await get_station_summary(session, station_id)


@router.get("/{station_id}/events", response_model=list[StationEventSummary])
async def get_station_events(
    station_id: int,
    session: SessionDep,
    limit: int = 50,
) -> list[StationEventSummary]:
    return await list_station_events(session, station_id, limit)


@router.patch("/{station_id}", response_model=StationResponse)
async def update_station(
    station_id: int,
    payload: StationUpdate,
    session: SessionDep,
) -> StationResponse:
    return await update_station_inventory(session, station_id, payload)


@router.patch("/{station_id}/config", response_model=StationSummary)
async def patch_station_config(
    station_id: int,
    payload: StationConfigUpdate,
    session: SessionDep,
) -> StationSummary:
    return await update_station_config(session, station_id, payload)


@router.put("/{station_id}/measurement-types", response_model=StationSummary)
async def put_station_measurement_types(
    station_id: int,
    payload: StationMeasurementTypeUpdate,
    session: SessionDep,
) -> StationSummary:
    return await replace_admin_station_measurement_types(
        session,
        station_id,
        payload.measurement_type_codes,
    )
