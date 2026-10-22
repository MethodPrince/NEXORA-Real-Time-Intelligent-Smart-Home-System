import logging
from typing import NoReturn
from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Response
from sqlalchemy import delete
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.schemas.devices import DeviceCreate
from app.api.schemas.devices import DeviceRead
from app.api.schemas.devices import DeviceUpdate
from app.db.dependencies import get_db_session
from app.db.models import Device

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
) -> Device:
    device = Device(**device_data.model_dump())
    try:
        session.add(device)
        session.commit()
        session.refresh(device)
    except SQLAlchemyError as error:
        session.rollback()
        _raise_database_error("creation", error)
    return device


@router.get("", response_model=list[DeviceRead])
def list_devices(session: Session = Depends(get_db_session)) -> list[Device]:
    try:
        statement = select(Device).order_by(Device.created_at, Device.id)
        return list(session.scalars(statement))
    except SQLAlchemyError as error:
        _raise_database_error("listing", error)


@router.get("/{device_id}", response_model=DeviceRead)
def get_device(
    device_id: UUID,
    session: Session = Depends(get_db_session),
) -> Device:
    try:
        device = session.get(Device, device_id)
    except SQLAlchemyError as error:
        _raise_database_error("retrieval", error)
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")
    return device


@router.patch("/{device_id}", response_model=DeviceRead)
def update_device(
    device_id: UUID,
    device_data: DeviceUpdate,
    session: Session = Depends(get_db_session),
) -> Device:
    try:
        device = session.get(Device, device_id)
        if device is None:
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
    session: Session = Depends(get_db_session),
) -> Response:
    try:
        result = session.execute(delete(Device).where(Device.id == device_id))
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Device not found")
        session.commit()
    except HTTPException:
        raise
    except SQLAlchemyError as error:
        session.rollback()
        _raise_database_error("deletion", error)
    return Response(status_code=204)
