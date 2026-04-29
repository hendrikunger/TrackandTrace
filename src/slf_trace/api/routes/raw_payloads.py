from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from slf_trace.api.schemas.admin import RawPayloadDetail
from slf_trace.api.services.admin import get_raw_payload_detail
from slf_trace.db import get_session

router = APIRouter(prefix="/raw-payloads", tags=["admin"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("/{raw_payload_id}", response_model=RawPayloadDetail)
async def get_raw_payload(
    raw_payload_id: int,
    session: SessionDep,
) -> RawPayloadDetail:
    return await get_raw_payload_detail(session, raw_payload_id)
