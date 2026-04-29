import pytest
from httpx import ASGITransport, AsyncClient

from slf_trace.api.events import EventHub, LiveEvent
from slf_trace.api.main import app


class RecordingWebSocket:
    def __init__(self) -> None:
        self.accepted = False
        self.messages = []

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, payload):
        self.messages.append(payload)


def test_live_event_shape() -> None:
    event = LiveEvent(
        type="measurement.captured",
        station_id=1,
        payload={"measurement_id": 10},
    )

    assert event.as_dict() == {
        "type": "measurement.captured",
        "station_id": 1,
        "payload": {"measurement_id": 10},
    }


@pytest.mark.asyncio
async def test_event_hub_broadcasts_to_connected_clients() -> None:
    hub = EventHub()
    websocket = RecordingWebSocket()

    await hub.connect(websocket)
    await hub.broadcast(LiveEvent(type="station.heartbeat", station_id=1, payload={}))

    assert websocket.accepted is True
    assert websocket.messages == [
        {
            "type": "station.heartbeat",
            "station_id": 1,
            "payload": {},
        }
    ]


@pytest.mark.asyncio
async def test_live_websocket_route_is_registered() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/openapi.json")

    assert response.status_code == 200
    websocket_routes = {
        getattr(route, "path", None)
        for route in app.routes
        if getattr(route, "path", None)
    }
    assert "/api/live/events" in websocket_routes
