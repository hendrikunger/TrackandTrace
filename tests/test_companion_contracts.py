from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from slf_trace.api.main import app
from slf_trace.api.routes import companion as companion_routes
from slf_trace.api.schemas.companion import (
    MeasurementRequest,
    RawPayloadRequest,
    StationConfigResponse,
    StationEventRequest,
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
        scanner_host="10.0.0.21",
        scanner_port=9004,
        scanner_protocol="Keyence SR-X TCP",
        workflow_type="measurement_capture",
        workflow_title="Breite messen",
        workflow_config={"mode": "touch"},
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
    assert config.workflow_title == "Breite messen"
    assert config.workflow_config == {"mode": "touch"}
    assert config.scanner_port == 9004


def test_station_event_requires_diagnostic_message() -> None:
    event = StationEventRequest(
        station_id=1,
        event_type="parser.failure",
        severity="error",
        message="Parser rejected payload.",
        context={"raw_payload_id": 5},
    )

    assert event.severity == "error"
    assert event.context == {"raw_payload_id": 5}


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
    assert "/api/companion/events" in paths
    assert "/api/companion/barcode-scans" in paths
    assert "/api/companion/raw-payloads" in paths
    assert "/api/companion/measurements" in paths
    assert "/api/companion/parsed-measurements" in paths
    assert "/api/companion/stations/{station_id}/config" in paths


@pytest.mark.asyncio
async def test_barcode_scan_api_returns_part_and_publishes_event(monkeypatch) -> None:
    published = []

    async def record_barcode_scan(session, payload):
        assert payload.rueckmeldenummer == "RM-API-1"
        return SimpleNamespace(id=42, rueckmeldenummer=payload.rueckmeldenummer), True

    async def publish_event(event_type, station_id, payload):
        published.append((event_type, station_id, payload))

    monkeypatch.setattr(companion_routes, "record_barcode_scan", record_barcode_scan)
    monkeypatch.setattr(companion_routes, "publish_event", publish_event)
    app.dependency_overrides[get_session] = _fake_session
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/companion/barcode-scans",
                json={
                    "station_id": 1,
                    "rueckmeldenummer": "RM-API-1",
                    "source_type": "keyence_srx_simulator",
                    "raw_payload": "RM-API-1",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "status": "accepted",
        "part_id": 42,
        "rueckmeldenummer": "RM-API-1",
        "created": True,
    }
    assert published[0][0] == "barcode.scan"
    assert published[0][2]["created"] is True


@pytest.mark.asyncio
async def test_measurement_api_surfaces_duplicate_idempotency(monkeypatch) -> None:
    published = []
    measurement = SimpleNamespace(
        id=101,
        station_id=1,
        part_id=42,
        idempotency_key="event-duplicate",
        values=[SimpleNamespace(measurement_type="breite")],
    )

    async def record_measurement(session, payload):
        assert payload.idempotency_key == "event-duplicate"
        return measurement, True

    async def publish_event(event_type, station_id, payload):
        published.append((event_type, station_id, payload))

    monkeypatch.setattr(companion_routes, "record_measurement", record_measurement)
    monkeypatch.setattr(companion_routes, "publish_event", publish_event)
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
                    "idempotency_key": "event-duplicate",
                    "source_type": "api_simulator",
                    "measured_at": datetime.now(UTC).isoformat(),
                    "rueckmeldenummer": "RM-API-1",
                    "values": [{"measurement_type": "breite", "value": "12.4"}],
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "status": "accepted",
        "measurement_id": 101,
        "part_id": 42,
        "duplicate": True,
        "values_count": 1,
    }
    assert published[0][0] == "measurement.captured"
    assert published[0][2]["duplicate"] is True
