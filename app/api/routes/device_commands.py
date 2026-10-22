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

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/devices", tags=["device commands"])


def get_mqtt_service(request: Request) -> MQTTService:
    return request.app.state.mqtt_service


@router.post(
    "/{device_id}/command",
    response_model=DeviceCommandAccepted,
    status_code=202,
)
def publish_device_command(
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
