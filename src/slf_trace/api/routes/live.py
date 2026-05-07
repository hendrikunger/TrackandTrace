from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from slf_trace.api.events import event_hub

router = APIRouter(prefix="/live", tags=["live"])


@router.websocket("/events")
async def live_events(websocket: WebSocket) -> None:
    await event_hub.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        event_hub.disconnect(websocket)
