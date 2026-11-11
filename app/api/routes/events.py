from fastapi import APIRouter
from fastapi import Depends

from app.db.dependencies import HomeAccess
from app.db.dependencies import require_admin
from app.websocket.connection_manager import connection_manager
from app.websocket.events import SystemEvent

router = APIRouter(prefix="/events", tags=["events"])


@router.post("/test", response_model=SystemEvent)
async def trigger_test_event(access: HomeAccess = Depends(require_admin)) -> SystemEvent:
    """Broadcast a development event to connected clients in the selected home."""
    event = SystemEvent.test_event()
    await connection_manager.broadcast_to_home(
        access.home.id,
        event.model_dump(mode="json"),
    )
    return event
