import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi import WebSocket
from fastapi import WebSocketDisconnect

from app.api.routes.automations import router as automations_router
from app.api.routes.device_commands import router as device_commands_router
from app.api.routes.devices import router as devices_router
from app.api.routes.events import router as events_router
from app.api.routes.health import router as health_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.services.mqtt import MQTTService
from app.services.automation_scheduler import AutomationScheduler
from app.websocket.connection_manager import connection_manager

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    mqtt_service = MQTTService(get_settings())
    application.state.mqtt_service = mqtt_service
    mqtt_service.start()
    automation_scheduler = AutomationScheduler(mqtt_service)
    application.state.automation_scheduler = automation_scheduler
    automation_scheduler.start()
    try:
        yield
    finally:
        await automation_scheduler.stop()
        await mqtt_service.stop()


app = FastAPI(
    title=settings.app_name,
    description="Real-time Python backend foundation for NEXORA.",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(health_router)
app.include_router(automations_router)
app.include_router(devices_router)
app.include_router(device_commands_router)
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
