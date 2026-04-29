from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from slf_trace.api.schemas.admin import PartMeasurementHistory
from slf_trace.api.services.admin import get_measurement_history
from slf_trace.db import get_session

router = APIRouter(prefix="/parts", tags=["admin"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("/{rueckmeldenummer}/measurements", response_model=PartMeasurementHistory)
async def get_part_measurements(
    rueckmeldenummer: str,
    session: SessionDep,
    station_id: int | None = Query(default=None),
) -> PartMeasurementHistory:
    return await get_measurement_history(session, rueckmeldenummer, station_id)
