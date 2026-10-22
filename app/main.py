import logging

from fastapi import FastAPI
from fastapi import WebSocket
from fastapi import WebSocketDisconnect

from app.api.routes.events import router as events_router
from app.api.routes.health import router as health_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.websocket.connection_manager import connection_manager

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.app_name,
    description="Real-time Python backend foundation for NEXORA.",
    version="0.1.0",
)
app.include_router(health_router)
app.include_router(events_router)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await connection_manager.connect(websocket)
    logger.info("WebSocket client connected")

    try:
        while True:
            message = await websocket.receive_text()
            await connection_manager.send_personal_message(
                f"NEXORA received: {message}",
                websocket,
            )
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    finally:
        await connection_manager.disconnect(websocket)
