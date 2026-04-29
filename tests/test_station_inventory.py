import pytest
from httpx import ASGITransport, AsyncClient

from slf_trace.api.main import app
from slf_trace.db import get_session


async def _fake_session():
    yield object()


@pytest.mark.asyncio
async def test_station_create_validates_measurement_type_codes() -> None:
    app.dependency_overrides[get_session] = _fake_session
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/stations",
                json={
                    "name": "Station A",
                    "scanner_port": 70000,
                    "measurement_type_codes": ["breite"],
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_station_inventory_routes_are_registered() -> None:
    app.dependency_overrides[get_session] = _fake_session
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get("/openapi.json")
    finally:
        app.dependency_overrides.clear()

    paths = response.json()["paths"]
    assert "/api/stations" in paths
    assert "/api/stations/{station_id}" in paths
