from fastapi import APIRouter

from slf_trace.api.routes import companion, live, measurement_types, parts, raw_payloads, stations

router = APIRouter(prefix="/api")
router.include_router(companion.router)
router.include_router(live.router)
router.include_router(measurement_types.router)
router.include_router(parts.router)
router.include_router(raw_payloads.router)
router.include_router(stations.router)
