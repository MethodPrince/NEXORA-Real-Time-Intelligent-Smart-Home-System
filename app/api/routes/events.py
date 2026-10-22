from fastapi import APIRouter

from app.websocket.connection_manager import connection_manager
from app.websocket.events import SystemEvent

router = APIRouter(prefix="/events", tags=["events"])


@router.post("/test", response_model=SystemEvent)
async def trigger_test_event() -> SystemEvent:
    """Broadcast a development event to every connected WebSocket client."""
    event = SystemEvent.test_event()
    await connection_manager.broadcast(event.model_dump(mode="json"))
    return event
