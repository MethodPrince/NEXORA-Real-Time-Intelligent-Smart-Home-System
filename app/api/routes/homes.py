import logging
from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Request
from sqlalchemy import delete
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.schemas.homes import HomeCreate
from app.api.schemas.homes import HomeRead
from app.db.dependencies import HomeAccess
from app.db.dependencies import get_current_user
from app.db.dependencies import get_db_session
from app.db.dependencies import require_admin
from app.db.models import ActivityLog
from app.db.models import AutomationRule
from app.db.models import Device
from app.db.models import DeviceAccess
from app.db.models import Home
from app.db.models import HomeMembership
from app.db.models import SecurityEvent
from app.db.models import Sensor
from app.db.models import User
from app.services.security_events import add_security_event
from app.websocket.connection_manager import connection_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/homes", tags=["homes"])


@router.get("", response_model=list[HomeRead])
def list_homes(
    session: Session = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> list[HomeRead]:
    memberships = session.execute(
        select(Home, HomeMembership.role)
        .join(HomeMembership, HomeMembership.home_id == Home.id)
        .where(
            HomeMembership.user_id == user.id,
            HomeMembership.is_active.is_(True),
        )
        .order_by(Home.name, Home.id)
    )
    return [
        HomeRead(id=home.id, name=home.name, role=role)
        for home, role in memberships
    ]


@router.post("", response_model=HomeRead, status_code=201)
def create_home(
    data: HomeCreate,
    request: Request,
    session: Session = Depends(get_db_session),
    creator: HomeAccess = Depends(require_admin),
) -> HomeRead:
    home = Home(name=data.name.strip())
    membership = HomeMembership(
        user_id=creator.user.id,
        home=home,
        role=creator.role,
    )
    session.add_all([home, membership])
    try:
        session.flush()
        add_security_event(
            session,
            event_type="home_created",
            severity="info",
            source="/homes",
            outcome="success",
            user_id=creator.user.id,
            home_id=home.id,
            request=request,
            metadata={"home_name": home.name},
        )
        session.commit()
    except SQLAlchemyError as error:
        session.rollback()
        logger.exception("Home creation failed")
        raise HTTPException(status_code=503, detail="Home service unavailable") from error
    return HomeRead(id=home.id, name=home.name, role=creator.role)


@router.delete("/{home_id}", status_code=204)
async def delete_home(
    home_id: UUID,
    request: Request,
    session: Session = Depends(get_db_session),
    access: HomeAccess = Depends(require_admin),
) -> None:
    if home_id != access.home.id:
        raise HTTPException(status_code=404, detail="Home not found")

    remaining_home_id = session.scalar(
        select(HomeMembership.home_id)
        .where(
            HomeMembership.user_id == access.user.id,
            HomeMembership.home_id != home_id,
            HomeMembership.is_active.is_(True),
        )
        .limit(1)
    )
    if remaining_home_id is None:
        raise HTTPException(
            status_code=409,
            detail="At least one home must remain accessible to delete a home",
        )

    home_name = access.home.name
    member_ids = list(
        session.scalars(
            select(HomeMembership.user_id).where(HomeMembership.home_id == home_id)
        )
    )
    device_ids = list(
        session.scalars(select(Device.id).where(Device.home_id == home_id))
    )
    add_security_event(
        session,
        event_type="home_deleted",
        severity="warning",
        source="/homes/{home_id}",
        outcome="success",
        user_id=access.user.id,
        home_id=home_id,
        request=request,
        metadata={"home_id": str(home_id), "home_name": home_name},
    )

    try:
        session.flush()
        session.execute(
            update(SecurityEvent)
            .where(SecurityEvent.home_id == home_id)
            .values(home_id=None)
        )
        session.execute(delete(ActivityLog).where(ActivityLog.home_id == home_id))
        session.execute(
            delete(AutomationRule).where(AutomationRule.home_id == home_id)
        )
        if device_ids:
            session.execute(delete(Sensor).where(Sensor.device_id.in_(device_ids)))
            session.execute(
                delete(DeviceAccess).where(DeviceAccess.device_id.in_(device_ids))
            )
        session.execute(delete(Device).where(Device.home_id == home_id))
        session.execute(
            delete(HomeMembership).where(HomeMembership.home_id == home_id)
        )
        session.execute(delete(Home).where(Home.id == home_id))
        session.commit()
    except SQLAlchemyError as error:
        session.rollback()
        logger.exception("Home deletion failed")
        raise HTTPException(status_code=503, detail="Home service unavailable") from error

    for member_id in member_ids:
        await connection_manager.disconnect_user_home(member_id, home_id)
