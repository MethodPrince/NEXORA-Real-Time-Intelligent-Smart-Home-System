from typing import Annotated

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Request
from fastapi import status
from sqlalchemy import and_
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas.private_data import ActivityLogRead
from app.api.schemas.private_data import SensorRead
from app.db.dependencies import HomeAccess
from app.db.dependencies import get_current_home
from app.db.dependencies import get_db_session
from app.db.models import ActivityLog
from app.db.models import Device
from app.db.models import DeviceAccess
from app.db.models import Sensor
from app.db.models import HomeRole
from app.services.security_events import record_security_event

router = APIRouter(tags=["private data"])


@router.get("/sensors", response_model=list[SensorRead])
def list_sensors(
    session: Annotated[Session, Depends(get_db_session)],
    access: Annotated[HomeAccess, Depends(get_current_home)],
) -> list[Sensor]:
    statement = (
        select(Sensor)
        .join(Device, Sensor.device_id == Device.id)
        .where(Device.home_id == access.home.id)
    )
    if access.role != HomeRole.ADMIN:
        statement = statement.where(
            Device.id.in_(
                select(DeviceAccess.device_id).where(
                    DeviceAccess.user_id == access.user.id
                )
            )
        )
    statement = statement.order_by(Sensor.timestamp.desc()).limit(500)
    return list(session.scalars(statement))


@router.get("/activity", response_model=list[ActivityLogRead])
def list_activity(
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
    access: Annotated[HomeAccess, Depends(get_current_home)],
) -> list[ActivityLog]:
    if access.role == HomeRole.GUEST:
        record_security_event(
            session,
            event_type="access_denied",
            severity="warning",
            source="/activity",
            outcome="denied",
            user_id=access.user.id,
            home_id=access.home.id,
            request=request,
            metadata={"reason": "guest_activity_restricted"},
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Activity logs are not available to guests",
        )
    if access.role == HomeRole.ADMIN:
        return list(
            session.scalars(
                select(ActivityLog)
                .where(ActivityLog.home_id == access.home.id)
                .order_by(ActivityLog.timestamp.desc())
                .limit(500)
            )
        )
    accessible_device_ids = select(DeviceAccess.device_id).where(
        DeviceAccess.user_id == access.user.id
    )
    statement = (
        select(ActivityLog)
        .where(
            ActivityLog.home_id == access.home.id,
            or_(
                ActivityLog.user_id == access.user.id,
                and_(
                    ActivityLog.user_id.is_(None),
                    ActivityLog.device_id.in_(accessible_device_ids),
                ),
                ActivityLog.device_id.in_(accessible_device_ids),
            )
        )
        .order_by(ActivityLog.timestamp.desc())
        .limit(500)
    )
    return list(session.scalars(statement))
