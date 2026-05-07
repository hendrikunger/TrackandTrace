import logging
from dataclasses import dataclass
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class LiveEvent:
    type: str
    station_id: int
    payload: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "station_id": self.station_id,
            "payload": self.payload,
        }


class EventHub:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections.discard(websocket)

    async def broadcast(self, event: LiveEvent) -> None:
        stale_connections = []
        for websocket in list(self._connections):
            try:
                await websocket.send_json(event.as_dict())
            except Exception as exc:  # noqa: BLE001 - websocket backends raise mixed errors.
                logger.warning(
                    "Dropping stale live event connection",
                    extra={"error": exc.__class__.__name__, "event_type": event.type},
                )
                stale_connections.append(websocket)

        for websocket in stale_connections:
            self.disconnect(websocket)


event_hub = EventHub()


async def publish_event(event_type: str, station_id: int, payload: dict[str, Any]) -> None:
    await event_hub.broadcast(
        LiveEvent(
            type=event_type,
            station_id=station_id,
            payload=payload,
        )
    )
