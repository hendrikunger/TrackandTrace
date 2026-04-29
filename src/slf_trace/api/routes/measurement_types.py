from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from slf_trace.api.schemas.admin import MeasurementTypeSummary
from slf_trace.api.services.admin import list_measurement_types
from slf_trace.db import get_session

router = APIRouter(prefix="/measurement-types", tags=["admin"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("", response_model=list[MeasurementTypeSummary])
async def get_measurement_types(session: SessionDep) -> list[MeasurementTypeSummary]:
    return await list_measurement_types(session)
