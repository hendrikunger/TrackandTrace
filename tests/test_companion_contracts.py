from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from slf_trace.api.main import app
from slf_trace.api.schemas.companion import (
    MeasurementRequest,
    RawPayloadRequest,
    StationConfigResponse,
)
from slf_trace.db import get_session


async def _fake_session():
    yield object()


def test_measurement_requires_part_reference() -> None:
    with pytest.raises(ValidationError, match="Either part_id or rueckmeldenummer is required"):
        MeasurementRequest(
            station_id=1,
            idempotency_key="event-1",
            source_type="simulator",
            measured_at=datetime.now(UTC),
            values=[{"measurement_type": "breite", "value": "3.3"}],
        )


def test_raw_payload_accepts_hashless_content() -> None:
    payload = RawPayloadRequest(
        station_id=1,
        source_type="simulator",
        content="A=1;I=2;B=3;U=4",
    )

    assert payload.payload_hash is None


def test_station_config_can_include_allowed_measurement_types() -> None:
    config = StationConfigResponse(
        station_id=1,
        name="Station 1",
        active=True,
        adapters=[
            {
                "type": "smb1_polling",
                "remote_dir": "/ExcelAusgabe",
                "share": "MEASURE",
            }
        ],
        measurement_types=[
            {"code": "breite", "label": "Breite", "unit": "mm"},
        ],
    )

    assert config.measurement_types[0].code == "breite"
    assert config.adapters[0]["remote_dir"] == "/ExcelAusgabe"


@pytest.mark.asyncio
async def test_measurement_route_validates_body_before_handler() -> None:
    app.dependency_overrides[get_session] = _fake_session
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/companion/measurements",
                json={
                    "station_id": 1,
                    "idempotency_key": "event-1",
                    "source_type": "simulator",
                    "measured_at": datetime.now(UTC).isoformat(),
                    "values": [{"measurement_type": "breite", "value": "3.3"}],
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422


def test_measurement_requires_at_least_one_value() -> None:
    with pytest.raises(ValidationError):
        MeasurementRequest(
            station_id=1,
            idempotency_key="event-1",
            source_type="simulator",
            measured_at=datetime.now(UTC),
            rueckmeldenummer="RM-123",
            values=[],
        )


@pytest.mark.asyncio
async def test_companion_routes_are_registered() -> None:
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
    assert "/api/companion/heartbeats" in paths
    assert "/api/companion/barcode-scans" in paths
    assert "/api/companion/raw-payloads" in paths
    assert "/api/companion/measurements" in paths
    assert "/api/companion/parsed-measurements" in paths
    assert "/api/companion/stations/{station_id}/config" in paths
