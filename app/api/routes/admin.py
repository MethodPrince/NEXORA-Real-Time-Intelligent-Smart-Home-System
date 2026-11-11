import logging
from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Request
from fastapi import Response
from sqlalchemy import delete
from sqlalchemy import func
from sqlalchemy import and_
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.schemas.admin import AdminUserCreate
from app.api.schemas.admin import AdminUserUpdate
from app.api.schemas.admin import DeviceGrantList
from app.api.schemas.admin import DeviceGrantRead
from app.api.schemas.admin import SecuritySettingsUpdate
from app.api.schemas.auth import UserRead
from app.core.config import get_settings
from app.db.dependencies import HomeAccess
from app.db.dependencies import get_db_session
from app.db.dependencies import require_admin
from app.db.models import ActivityLog
from app.db.models import Device
from app.db.models import DeviceAccess
from app.db.models import HomeMembership
from app.db.models import HomeRole
from app.db.models import SecurityEvent
from app.db.models import SystemSettings
from app.db.models import User
from app.db.models import UserRole
from app.services.auth import hash_password
from app.services.security_events import add_security_event
from app.services.security_events import record_security_event
from app.websocket.connection_manager import connection_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["administration"])


def _last_active_admin(session: Session, home_id: UUID, user_id: UUID) -> bool:
    count = session.scalar(
        select(func.count(HomeMembership.user_id))
        .join(User, User.id == HomeMembership.user_id)
        .where(
            HomeMembership.home_id == home_id,
            HomeMembership.role == HomeRole.ADMIN,
            HomeMembership.is_active.is_(True),
            User.is_active.is_(True),
            HomeMembership.user_id != user_id,
        )
    )
    return bool(count)


def _home_user_read(user: User, membership: HomeMembership) -> UserRead:
    return UserRead(
        id=user.id,
        name=user.name,
        email=user.email,
        role=UserRole(membership.role.value),
        is_active=user.is_active and membership.is_active,
    )


def _record_admin_target_denial(
    session: Session,
    request: Request,
    access: HomeAccess,
    *,
    action: str,
    target_id: UUID,
) -> None:
    record_security_event(
        session,
        event_type="access_denied",
        severity="warning",
        source=request.url.path,
        outcome="denied",
        user_id=access.user.id,
        home_id=access.home.id,
        request=request,
        metadata={
            "action": action,
            "target_id": str(target_id),
            "reason": "target_not_in_selected_home",
        },
    )


def _require_platform_admin(
    session: Session,
    request: Request,
    access: HomeAccess,
) -> None:
    if access.user.role == UserRole.ADMIN:
        return
    record_security_event(
        session,
        event_type="access_denied",
        severity="warning",
        source=request.url.path,
        outcome="denied",
        user_id=access.user.id,
        home_id=access.home.id,
        request=request,
        metadata={"reason": "platform_administrator_required"},
    )
    raise HTTPException(
        status_code=403,
        detail="Platform administrator access required",
    )


@router.get("/users", response_model=list[UserRead])
def list_users(
    session: Session = Depends(get_db_session),
    access: HomeAccess = Depends(require_admin),
) -> list[UserRead]:
    rows = session.execute(
        select(User, HomeMembership)
        .join(HomeMembership, HomeMembership.user_id == User.id)
        .where(HomeMembership.home_id == access.home.id)
        .order_by(User.created_at, User.id)
    )
    return [_home_user_read(user, membership) for user, membership in rows]


@router.post("/users", response_model=UserRead, status_code=201)
def create_user(
    user_data: AdminUserCreate,
    request: Request,
    session: Session = Depends(get_db_session),
    access: HomeAccess = Depends(require_admin),
) -> UserRead:
    email = str(user_data.email).strip().lower()
    user = session.scalar(select(User).where(User.email == email))
    is_new_user = user is None
    if user is None:
        user = User(
            name=user_data.name,
            email=email,
            password_hash=hash_password(user_data.password),
            role=UserRole.STANDARD_USER,
        )
        session.add(user)
        session.flush()
    membership = session.get(
        HomeMembership,
        {"user_id": user.id, "home_id": access.home.id},
    )
    if membership is not None:
        raise HTTPException(status_code=409, detail="User already belongs to this home")
    membership = HomeMembership(
        user_id=user.id,
        home_id=access.home.id,
        role=HomeRole(user_data.role.value),
    )
    session.add(membership)
    add_security_event(
        session,
        event_type="user_created" if is_new_user else "home_membership_created",
        severity="info",
        source="/admin/users",
        outcome="success",
        user_id=access.user.id,
        home_id=access.home.id,
        request=request,
        metadata={"target_user_id": str(user.id), "role": membership.role.value},
    )
    try:
        session.commit()
        session.refresh(user)
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists") from error
    except SQLAlchemyError as error:
        session.rollback()
        logger.exception("Administrator user creation failed")
        raise HTTPException(status_code=503, detail="Account service unavailable") from error
    return _home_user_read(user, membership)


@router.patch("/users/{user_id}", response_model=UserRead)
async def update_user(
    user_id: UUID,
    user_data: AdminUserUpdate,
    request: Request,
    session: Session = Depends(get_db_session),
    access: HomeAccess = Depends(require_admin),
) -> UserRead:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    membership = session.get(
        HomeMembership,
        {"user_id": user_id, "home_id": access.home.id},
    )
    if membership is None:
        _record_admin_target_denial(
            session,
            request,
            access,
            action="update_home_membership",
            target_id=user_id,
        )
        raise HTTPException(status_code=404, detail="User not found")
    changes = user_data.model_dump(exclude_unset=True)
    requested_role = changes.get("role")
    is_removing_admin = membership.role == HomeRole.ADMIN and (
        requested_role is not None
        and requested_role != UserRole.ADMIN
        or changes.get("is_active") is False
    )
    if is_removing_admin and not _last_active_admin(
        session,
        access.home.id,
        user.id,
    ):
        raise HTTPException(status_code=409, detail="At least one active administrator must remain")
    if user.id == access.user.id and changes:
        raise HTTPException(status_code=409, detail="Administrators cannot change their own account")
    if "role" in changes:
        membership.role = HomeRole(changes["role"].value)
    if "is_active" in changes:
        membership.is_active = changes["is_active"]
    event_type = (
        "user_deactivated"
        if changes.get("is_active") is False
        else "user_role_changed"
        if "role" in changes
        else "home_membership_updated"
    )
    add_security_event(
        session,
        event_type=event_type,
        severity="info",
        source="/admin/users/{user_id}",
        outcome="success",
        user_id=access.user.id,
        home_id=access.home.id,
        request=request,
        metadata={
            "target_user_id": str(user.id),
            "role": membership.role.value,
            "is_active": membership.is_active,
        },
    )
    try:
        session.commit()
        session.refresh(user)
        session.refresh(membership)
    except SQLAlchemyError as error:
        session.rollback()
        logger.exception("Administrator user update failed")
        raise HTTPException(status_code=503, detail="Account service unavailable") from error
    if not membership.is_active:
        await connection_manager.disconnect_user_home(user.id, access.home.id)
    return _home_user_read(user, membership)


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(
    user_id: UUID,
    request: Request,
    session: Session = Depends(get_db_session),
    access: HomeAccess = Depends(require_admin),
) -> Response:
    membership = session.get(
        HomeMembership,
        {"user_id": user_id, "home_id": access.home.id},
    )
    if membership is None:
        _record_admin_target_denial(
            session,
            request,
            access,
            action="remove_home_membership",
            target_id=user_id,
        )
        raise HTTPException(status_code=404, detail="User not found")
    if user_id == access.user.id:
        raise HTTPException(status_code=409, detail="Administrators cannot remove their own account")
    if membership.role == HomeRole.ADMIN and not _last_active_admin(
        session,
        access.home.id,
        user_id,
    ):
        raise HTTPException(status_code=409, detail="At least one active administrator must remain")
    add_security_event(
        session,
        event_type="home_membership_removed",
        severity="info",
        source="/admin/users/{user_id}",
        outcome="success",
        user_id=access.user.id,
        home_id=access.home.id,
        request=request,
        metadata={"target_user_id": str(user_id)},
    )
    try:
        session.execute(
            delete(DeviceAccess)
            .where(DeviceAccess.user_id == user_id)
            .where(
                DeviceAccess.device_id.in_(
                    select(Device.id).where(Device.home_id == access.home.id)
                )
            )
        )
        session.delete(membership)
        session.commit()
    except SQLAlchemyError as error:
        session.rollback()
        logger.exception("Administrator user deletion failed")
        raise HTTPException(status_code=503, detail="Account service unavailable") from error
    await connection_manager.disconnect_user_home(user_id, access.home.id)
    return Response(status_code=204)


@router.get("/users/{user_id}/device-access", response_model=list[DeviceGrantRead])
def list_device_access(
    user_id: UUID,
    request: Request,
    session: Session = Depends(get_db_session),
    access: HomeAccess = Depends(require_admin),
) -> list[DeviceGrantRead]:
    if session.get(
        HomeMembership,
        {"user_id": user_id, "home_id": access.home.id},
    ) is None:
        _record_admin_target_denial(
            session,
            request,
            access,
            action="list_device_grants",
            target_id=user_id,
        )
        raise HTTPException(status_code=404, detail="User not found")
    rows = session.execute(
        select(DeviceAccess, Device)
        .join(Device, Device.id == DeviceAccess.device_id)
        .where(
            DeviceAccess.user_id == user_id,
            Device.home_id == access.home.id,
        )
        .order_by(Device.name, Device.id)
    )
    return [
        DeviceGrantRead(
            device_id=grant.device_id,
            can_control=grant.can_control,
            name=device.name,
            room=device.room,
            device_type=device.device_type,
        )
        for grant, device in rows
    ]


@router.put("/users/{user_id}/device-access", response_model=list[DeviceGrantRead])
def replace_device_access(
    user_id: UUID,
    grant_data: DeviceGrantList,
    request: Request,
    session: Session = Depends(get_db_session),
    access: HomeAccess = Depends(require_admin),
) -> list[DeviceGrantRead]:
    membership = session.get(
        HomeMembership,
        {"user_id": user_id, "home_id": access.home.id},
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="User not found")
    if membership.role == HomeRole.ADMIN:
        raise HTTPException(status_code=422, detail="Device grants are for standard users and guests")
    device_ids = [grant.device_id for grant in grant_data.grants]
    devices = (
        list(
            session.scalars(
                select(Device).where(
                    Device.id.in_(device_ids),
                    Device.home_id == access.home.id,
                )
            )
        )
        if device_ids
        else []
    )
    if len(devices) != len(device_ids):
        raise HTTPException(status_code=404, detail="One or more devices were not found")
    try:
        session.execute(
            delete(DeviceAccess)
            .where(DeviceAccess.user_id == user_id)
            .where(
                DeviceAccess.device_id.in_(
                    select(Device.id).where(Device.home_id == access.home.id)
                )
            )
        )
        session.add_all(
            DeviceAccess(
                user_id=user_id,
                device_id=grant.device_id,
                can_control=grant.can_control,
            )
            for grant in grant_data.grants
        )
        add_security_event(
            session,
            event_type="device_access_grants_updated",
            severity="info",
            source="/admin/users/{user_id}/device-access",
            outcome="success",
            user_id=access.user.id,
            home_id=access.home.id,
            request=request,
            metadata={
                "target_user_id": str(user_id),
                "grant_count": len(grant_data.grants),
            },
        )
        session.commit()
    except SQLAlchemyError as error:
        session.rollback()
        logger.exception("Administrator device access update failed")
        raise HTTPException(status_code=503, detail="Device access service unavailable") from error
    return [
        DeviceGrantRead(
            device_id=grant.device_id,
            can_control=grant.can_control,
            name=device.name,
            room=device.room,
            device_type=device.device_type,
        )
        for grant in grant_data.grants
        for device in devices
        if device.id == grant.device_id
    ]


@router.get("/activity", response_model=list[dict[str, object]])
def list_all_activity(
    session: Session = Depends(get_db_session),
    access: HomeAccess = Depends(require_admin),
) -> list[dict[str, object]]:
    entries = session.scalars(
        select(ActivityLog)
        .where(ActivityLog.home_id == access.home.id)
        .order_by(ActivityLog.timestamp.desc())
        .limit(500)
    )
    return [
        {
            "id": entry.id,
            "user_id": entry.user_id,
            "device_id": entry.device_id,
            "source": entry.source,
            "event": entry.event,
            "action": entry.action,
            "result": entry.result,
            "timestamp": entry.timestamp,
        }
        for entry in entries
    ]


@router.get("/security-events", response_model=list[dict[str, object]])
def list_security_events(
    session: Session = Depends(get_db_session),
    access: HomeAccess = Depends(require_admin),
) -> list[dict[str, object]]:
    unassigned_event_scope = SecurityEvent.home_id.is_(None)
    if access.user.role != UserRole.ADMIN:
        unassigned_event_scope = and_(
            unassigned_event_scope,
            SecurityEvent.user_id.in_(
                select(HomeMembership.user_id).where(
                    HomeMembership.home_id == access.home.id,
                    HomeMembership.is_active.is_(True),
                )
            ),
        )
    events = session.scalars(
        select(SecurityEvent)
        .where(
            or_(
                SecurityEvent.home_id == access.home.id,
                unassigned_event_scope,
            )
        )
        .order_by(SecurityEvent.timestamp.desc())
        .limit(500)
    )
    return [
        {
            "id": event.id,
            "event_type": event.event_type,
            "severity": event.severity,
            "source": event.source,
            "response": event.response,
            "user_id": event.user_id,
            "home_id": event.home_id,
            "source_ip": event.source_ip,
            "outcome": event.outcome,
            "metadata": event.metadata_json,
            "timestamp": event.timestamp,
        }
        for event in events
    ]


@router.get("/security-settings", response_model=dict[str, object])
def security_settings(
    request: Request,
    session: Session = Depends(get_db_session),
    admin: HomeAccess = Depends(require_admin),
) -> dict[str, object]:
    _require_platform_admin(session, request, admin)
    settings = get_settings()
    runtime_settings = session.get(SystemSettings, 1)
    return {
        "access_token_expire_minutes": settings.access_token_expire_minutes,
        "cors_origins": settings.allowed_origins,
        "registration_enabled": (
            runtime_settings.registration_enabled if runtime_settings is not None else True
        ),
        "admin_bootstrap_available": False,
        "jwt_secret_configured": bool(settings.jwt_secret_key),
    }


@router.patch("/security-settings", response_model=dict[str, object])
def update_security_settings(
    values: SecuritySettingsUpdate,
    request: Request,
    session: Session = Depends(get_db_session),
    admin: HomeAccess = Depends(require_admin),
) -> dict[str, object]:
    _require_platform_admin(session, request, admin)
    runtime_settings = session.get(SystemSettings, 1)
    if runtime_settings is None:
        runtime_settings = SystemSettings(id=1)
        session.add(runtime_settings)
    runtime_settings.registration_enabled = values.registration_enabled
    try:
        session.commit()
    except SQLAlchemyError as error:
        session.rollback()
        logger.exception("Administrator security settings update failed")
        raise HTTPException(status_code=503, detail="Settings service unavailable") from error
    return security_settings(request, session, admin)
