import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.schemas.mqtt import DeviceCommandAccepted
from app.api.schemas.mqtt import DeviceCommandRequest
from app.db.dependencies import get_db_session
from app.db.models import Device
from app.services.mqtt import MQTTService
from app.services.mqtt import MQTTServiceUnavailableError
from app.services.simulator import InvalidSimulatedCommandError
from app.services.simulator import apply_command
from app.services.simulator import device_kind
from app.services.simulator import display_status
from app.services.simulator import encode_state
from app.services.simulator import is_simulated
from app.services.simulator import simulated_state
from app.websocket.connection_manager import connection_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/devices", tags=["device commands"])


def get_mqtt_service(request: Request) -> MQTTService:
    return request.app.state.mqtt_service


@router.post(
    "/{device_id}/command",
    response_model=DeviceCommandAccepted,
    response_model_exclude_none=True,
    status_code=202,
)
async def publish_device_command(
    device_id: UUID,
    command_data: DeviceCommandRequest,
    session: Annotated[Session, Depends(get_db_session)],
    mqtt_service: Annotated[MQTTService, Depends(get_mqtt_service)],
) -> DeviceCommandAccepted:
    try:
        device = session.get(Device, device_id)
    except SQLAlchemyError as error:
        logger.exception("Unable to look up device for MQTT command")
        raise HTTPException(
            status_code=503,
            detail="Database operation unavailable",
        ) from error
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")

    if is_simulated(device):
        if not device.online:
            raise HTTPException(
                status_code=503,
                detail="Simulated device is offline",
            )
        kind = device_kind(device.device_type)
        current_state = simulated_state(device)
        if kind is None or current_state is None:
            raise HTTPException(
                status_code=503,
                detail="Simulated device state is unavailable",
            )
        try:
            state = apply_command(
                kind,
                current_state,
                command_data.command,
                command_data.parameters,
            )
        except InvalidSimulatedCommandError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

        device.status = encode_state(state)
        try:
            session.commit()
            session.refresh(device)
        except SQLAlchemyError as error:
            session.rollback()
            logger.exception("Unable to save simulated device state")
            raise HTTPException(
                status_code=503,
                detail="Database operation unavailable",
            ) from error

        status = display_status(kind, state)
        event = {
            "type": "device_state",
            "device_id": str(device_id),
            "status": status,
            "online": device.online,
            "state": state,
            "timestamp": device.updated_at.isoformat(),
        }
        await connection_manager.broadcast(event)
        return DeviceCommandAccepted(
            device_id=device_id,
            status="applied",
            online=device.online,
            state=state,
        )

    try:
        topic = mqtt_service.publish_device_command(
            device_id,
            command_data.command,
            command_data.parameters,
        )
    except MQTTServiceUnavailableError as error:
        raise HTTPException(
            status_code=503,
            detail="MQTT broker is unavailable",
        ) from error

    return DeviceCommandAccepted(
        device_id=device_id,
        topic=topic,
        status="queued",
    )
