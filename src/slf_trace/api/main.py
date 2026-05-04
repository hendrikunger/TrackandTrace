from contextlib import asynccontextmanager
from typing import Annotated

import uvicorn
from fastapi import FastAPI, Query

from slf_trace import __version__
from slf_trace.api.routes import router
from slf_trace.config import get_settings
from slf_trace.db import check_database


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.settings = get_settings()
    yield


app = FastAPI(
    title="SLF Track and Trace",
    version=__version__,
    lifespan=lifespan,
)
app.include_router(router)


@app.get("/")
async def root() -> dict[str, str]:
    return {"name": "SLF Track and Trace", "version": __version__}


@app.get("/health")
async def health(
    database: Annotated[bool, Query()] = True,
) -> dict[str, object]:
    settings = get_settings()
    database_status = {"ok": None, "skipped": True}
    if database:
        database_status = await check_database(settings)

    return {
        "status": "ok" if database_status.get("ok") in (True, None) else "degraded",
        "environment": settings.app_env,
        "database": database_status,
    }


def run() -> None:
    settings = get_settings()
    uvicorn.run(
        "slf_trace.api.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.app_env == "development",
    )
