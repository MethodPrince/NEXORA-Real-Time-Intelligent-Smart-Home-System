import logging
from typing import NoReturn
from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Request
from fastapi import Response
from sqlalchemy import select
from sqlalchemy import delete
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.schemas.devices import DeviceCreate
from app.api.schemas.devices import DeviceRead
from app.api.schemas.devices import DeviceUpdate
from app.db.dependencies import HomeAccess
from app.db.dependencies import get_current_home
from app.db.dependencies import get_db_session
from app.db.dependencies import require_admin
from app.db.models import Device
from app.db.models import DeviceAccess
from app.services.simulator import device_kind
from app.services.simulator import encode_state
from app.services.simulator import initial_state
from app.services.security_events import record_security_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/devices", tags=["devices"])


def _raise_database_error(operation: str, error: SQLAlchemyError) -> NoReturn:
    logger.exception("Device %s failed", operation)
    raise HTTPException(
        status_code=503,
        detail="Database operation unavailable",
    ) from error


@router.post("", response_model=DeviceRead, status_code=201)
def create_device(
    device_data: DeviceCreate,
    session: Session = Depends(get_db_session),
    access: HomeAccess = Depends(require_admin),
) -> Device:
    values = device_data.model_dump(exclude={"simulated"})
    values["owner_user_id"] = access.user.id
    values["home_id"] = access.home.id
    if device_data.simulated:
        kind = device_kind(device_data.device_type)
        if kind is None:
            raise HTTPException(
                status_code=422,
                detail="Simulated devices must be a light, fan, or curtain",
            )
        values["status"] = encode_state(initial_state(kind))
        if "online" not in device_data.model_fields_set:
            values["online"] = True
    device = Device(**values)
    try:
        session.add(device)
        session.commit()
        session.refresh(device)
    except SQLAlchemyError as error:
        session.rollback()
        _raise_database_error("creation", error)
    return device


@router.get("", response_model=list[DeviceRead])
def list_devices(
    session: Session = Depends(get_db_session),
    access: HomeAccess = Depends(get_current_home),
) -> list[Device]:
    try:
        statement = select(Device).where(Device.home_id == access.home.id)
        if access.role.value != "ADMIN":
            statement = statement.where(
                Device.id.in_(
                    select(DeviceAccess.device_id).where(
                        DeviceAccess.user_id == access.user.id
                    )
                )
            )
        statement = statement.order_by(Device.created_at, Device.id)
        return list(session.scalars(statement))
    except SQLAlchemyError as error:
        _raise_database_error("listing", error)


@router.get("/{device_id}", response_model=DeviceRead)
def get_device(
    device_id: UUID,
    request: Request,
    session: Session = Depends(get_db_session),
    access: HomeAccess = Depends(get_current_home),
) -> Device:
    try:
        device = session.scalar(
            select(Device).where(
                Device.id == device_id,
                Device.home_id == access.home.id,
            )
        )
    except SQLAlchemyError as error:
        _raise_database_error("retrieval", error)
    if device is None or (
        access.role.value != "ADMIN"
        and session.scalar(
            select(DeviceAccess.device_id).where(
                DeviceAccess.user_id == access.user.id,
                DeviceAccess.device_id == device_id,
            )
        )
        is None
    ):
        record_security_event(
            session,
            event_type="device_access_denied",
            severity="warning",
            source="/devices/{device_id}",
            outcome="denied",
            user_id=access.user.id,
            home_id=access.home.id,
            request=request,
            metadata={"device_id": str(device_id), "method": "GET"},
        )
        raise HTTPException(status_code=404, detail="Device not found")
    return device


@router.patch("/{device_id}", response_model=DeviceRead)
def update_device(
    device_id: UUID,
    request: Request,
    device_data: DeviceUpdate,
    session: Session = Depends(get_db_session),
    access: HomeAccess = Depends(require_admin),
) -> Device:
    try:
        device = session.scalar(
            select(Device).where(
                Device.id == device_id,
                Device.home_id == access.home.id,
            )
        )
        if device is None:
            record_security_event(
                session,
                event_type="device_management_denied",
                severity="warning",
                source="/devices/{device_id}",
                outcome="denied",
                user_id=access.user.id,
                home_id=access.home.id,
                request=request,
                metadata={"device_id": str(device_id), "method": "PATCH"},
            )
            raise HTTPException(status_code=404, detail="Device not found")
        for field_name, value in device_data.model_dump(exclude_unset=True).items():
            setattr(device, field_name, value)
        session.commit()
        session.refresh(device)
    except HTTPException:
        raise
    except SQLAlchemyError as error:
        session.rollback()
        _raise_database_error("update", error)
    return device


@router.delete("/{device_id}", status_code=204)
def delete_device(
    device_id: UUID,
    request: Request,
    session: Session = Depends(get_db_session),
    access: HomeAccess = Depends(require_admin),
) -> Response:
    try:
        result = session.execute(
            delete(Device).where(
                Device.id == device_id,
                Device.home_id == access.home.id,
            )
        )
        if result.rowcount == 0:
            record_security_event(
                session,
                event_type="device_management_denied",
                severity="warning",
                source="/devices/{device_id}",
                outcome="denied",
                user_id=access.user.id,
                home_id=access.home.id,
                request=request,
                metadata={"device_id": str(device_id), "method": "DELETE"},
            )
            raise HTTPException(status_code=404, detail="Device not found")
        session.commit()
    except HTTPException:
        raise
    except SQLAlchemyError as error:
        session.rollback()
        _raise_database_error("deletion", error)
    return Response(status_code=204)
