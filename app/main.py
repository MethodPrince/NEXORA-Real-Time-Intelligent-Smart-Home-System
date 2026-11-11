import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi import Depends
from fastapi import WebSocket
from fastapi import WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session
from uuid import UUID

from app.api.routes.auth import router as auth_router
from app.api.routes.admin import router as admin_router
from app.api.routes.homes import router as homes_router
from app.api.routes.automations import router as automations_router
from app.api.routes.device_commands import router as device_commands_router
from app.api.routes.devices import router as devices_router
from app.api.routes.events import router as events_router
from app.api.routes.health import router as health_router
from app.api.routes.private_data import router as private_data_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.dependencies import get_db_session
from app.db.models import HomeMembership
from app.db.models import Home
from app.db.models import User
from app.services.mqtt import MQTTService
from app.services.automation_scheduler import AutomationScheduler
from app.services.auth import decode_access_token
from app.websocket.connection_manager import connection_manager
from app.services.security_events import record_security_event

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    if settings.environment.lower() in {"prod", "production"}:
        if not settings.jwt_secret_key:
            raise RuntimeError("NEXORA_JWT_SECRET_KEY is required in production")
        if not settings.database_url:
            raise RuntimeError("DATABASE_URL is required in production")
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
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Home-ID"],
)
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(homes_router)
app.include_router(health_router)
app.include_router(automations_router)
app.include_router(devices_router)
app.include_router(device_commands_router)
app.include_router(events_router)
app.include_router(private_data_router)


@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    session: Session = Depends(get_db_session),
) -> None:
    async def reject(reason: str, *, user_id: UUID | None = None, home_id: UUID | None = None) -> None:
        client_ip = websocket.client.host if websocket.client is not None else None
        valid_home_id = (
            home_id
            if home_id is not None and session.get(Home, home_id) is not None
            else None
        )
        try:
            record_security_event(
                session,
                event_type="websocket_authentication_failed",
                severity="warning",
                source="/ws",
                outcome="denied",
                user_id=user_id,
                home_id=valid_home_id,
                source_ip=client_ip,
                metadata={
                    "method": "WEBSOCKET",
                    "reason": reason,
                    **(
                        {"requested_home_id": str(home_id)}
                        if home_id is not None
                        else {}
                    ),
                },
            )
        finally:
            await websocket.close(code=4401, reason="WebSocket authorization failed")

    origin = websocket.headers.get("origin")
    if origin and origin not in settings.allowed_origins:
        await reject("origin_not_allowed")
        return
    raw_home_id = websocket.query_params.get("home_id")
    try:
        home_id = UUID(raw_home_id) if raw_home_id else None
    except ValueError:
        home_id = None
        await reject("invalid_home_id")
        return
    if home_id is None:
        await reject("missing_home_selection")
        return
    requested_protocols = [
        protocol.strip()
        for protocol in websocket.headers.get("sec-websocket-protocol", "").split(",")
    ]
    token = next(
        (protocol[len("bearer."):] for protocol in requested_protocols
         if protocol.startswith("bearer.")),
        None,
    )
    if token is None:
        await reject("missing_bearer_token", home_id=home_id)
        return
    try:
        user_id = decode_access_token(token, get_settings())
    except ValueError:
        await reject("invalid_or_expired_token", home_id=home_id)
        return
    user = session.get(User, user_id)
    if user is None or not user.is_active:
        await reject(
            "inactive_or_unknown_user",
            user_id=user_id,
            home_id=home_id,
        )
        return
    membership_exists = session.scalar(
        select(HomeMembership.user_id).where(
            HomeMembership.user_id == user.id,
            HomeMembership.home_id == home_id,
            HomeMembership.is_active.is_(True),
        )
    )
    if membership_exists is None:
        await reject(
            "not_a_home_member",
            user_id=user.id,
            home_id=home_id,
        )
        return
    await connection_manager.connect(websocket, user.id, home_id)
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
