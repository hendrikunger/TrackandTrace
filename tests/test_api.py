import pytest
from httpx import ASGITransport, AsyncClient

from slf_trace.api.main import app


@pytest.mark.asyncio
async def test_root_returns_application_identity() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/")

    assert response.status_code == 200
    assert response.json()["name"] == "SLF Track and Trace"


@pytest.mark.asyncio
async def test_health_can_skip_database_check() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/health?database=false")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == {"ok": None, "skipped": True}


@pytest.mark.asyncio
async def test_openapi_lists_admin_routes() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/api/stations" in paths
    assert "/api/stations/{station_id}" in paths
    assert "/api/stations/{station_id}/config" in paths
    assert "/api/stations/{station_id}/measurement-types" in paths
    assert "/api/measurement-types" in paths
    assert "/api/parts/{rueckmeldenummer}/measurements" in paths
    assert "/api/raw-payloads/{raw_payload_id}" in paths

    part_history_parameters = {
        parameter["name"]
        for parameter in paths["/api/parts/{rueckmeldenummer}/measurements"]["get"][
            "parameters"
        ]
    }
    assert {"rueckmeldenummer", "station_id"} <= part_history_parameters
