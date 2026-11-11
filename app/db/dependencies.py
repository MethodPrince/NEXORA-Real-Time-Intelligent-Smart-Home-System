from collections.abc import Generator
from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends
from fastapi import HTTPException
from fastapi import Request
from fastapi import status
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.security import HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Device
from app.db.models import DeviceAccess
from app.db.models import Home
from app.db.models import HomeMembership
from app.db.models import HomeRole
from app.db.models import User
from app.db.session import get_session
from app.services.auth import decode_access_token
from app.services.security_events import record_security_event


def get_db_session() -> Generator[Session, None, None]:
    yield from get_session()


bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class HomeAccess:
    user: User
    home: Home
    role: HomeRole


def _record_rejected_request(
    session: Session,
    request: Request,
    *,
    event_type: str,
    user_id: UUID | None = None,
    home_id: UUID | None = None,
    reason: str,
    requested_home_id: UUID | None = None,
) -> None:
    record_security_event(
        session,
        event_type=event_type,
        severity="warning",
        source=request.url.path,
        outcome="denied",
        user_id=user_id,
        home_id=home_id,
        request=request,
        metadata={
            "method": request.method,
            "reason": reason,
            **(
                {"requested_home_id": str(requested_home_id)}
                if requested_home_id is not None
                else {}
            ),
        },
    )


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: Session = Depends(get_db_session),
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        _record_rejected_request(
            session,
            request,
            event_type="api_authentication_failed",
            reason="missing_bearer_token",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        user_id = decode_access_token(credentials.credentials, get_settings())
    except ValueError as error:
        _record_rejected_request(
            session,
            request,
            event_type="api_authentication_failed",
            reason="invalid_or_expired_token",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from error
    user = session.get(User, user_id)
    if user is None or not user.is_active:
        _record_rejected_request(
            session,
            request,
            event_type="api_authentication_failed",
            user_id=user_id,
            reason="inactive_or_unknown_user",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    request.state.user_id = user.id
    return user


def get_current_home(
    request: Request,
    session: Session = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> HomeAccess:
    raw_home_id = request.headers.get("x-home-id")
    if not raw_home_id:
        _record_rejected_request(
            session,
            request,
            event_type="home_access_denied",
            user_id=user.id,
            reason="missing_home_selection",
        )
        raise HTTPException(status_code=400, detail="Select a home to continue")
    try:
        home_id = UUID(raw_home_id)
    except ValueError as error:
        _record_rejected_request(
            session,
            request,
            event_type="home_access_denied",
            user_id=user.id,
            reason="invalid_home_id",
        )
        raise HTTPException(status_code=400, detail="Invalid home selection") from error
    membership = session.execute(
        select(HomeMembership, Home)
        .join(Home, Home.id == HomeMembership.home_id)
        .where(
            HomeMembership.user_id == user.id,
            HomeMembership.home_id == home_id,
            HomeMembership.is_active.is_(True),
        )
    ).first()
    if membership is None:
        _record_rejected_request(
            session,
            request,
            event_type="home_access_denied",
            user_id=user.id,
            home_id=home_id if session.get(Home, home_id) is not None else None,
            reason="not_a_home_member",
            requested_home_id=home_id,
        )
        raise HTTPException(status_code=404, detail="Home not found")
    home_membership, home = membership
    request.state.home_id = home.id
    return HomeAccess(user=user, home=home, role=home_membership.role)


def require_admin(
    request: Request,
    session: Session = Depends(get_db_session),
    access: HomeAccess = Depends(get_current_home),
) -> HomeAccess:
    if access.role != HomeRole.ADMIN:
        _record_rejected_request(
            session,
            request,
            event_type="access_denied",
            user_id=access.user.id,
            home_id=access.home.id,
            reason="administrator_role_required",
        )
        raise HTTPException(status_code=403, detail="Administrator access required")
    return access


def require_non_guest(
    request: Request,
    session: Session = Depends(get_db_session),
    access: HomeAccess = Depends(get_current_home),
) -> HomeAccess:
    if access.role == HomeRole.GUEST:
        _record_rejected_request(
            session,
            request,
            event_type="access_denied",
            user_id=access.user.id,
            home_id=access.home.id,
            reason="guest_role_restricted",
        )
        raise HTTPException(status_code=403, detail="This feature is not available to guests")
    return access


def user_can_access_device(
    session: Session,
    user: User,
    device_id: UUID,
    *,
    control: bool = False,
    home_id: UUID | None = None,
) -> bool:
    device_home_id = session.scalar(
        select(Device.home_id).where(
            Device.id == device_id,
            *([Device.home_id == home_id] if home_id is not None else []),
        )
    )
    if device_home_id is None:
        return False
    membership_role = session.scalar(
        select(HomeMembership.role).where(
            HomeMembership.user_id == user.id,
            HomeMembership.home_id == device_home_id,
            HomeMembership.is_active.is_(True),
        )
    )
    if membership_role == HomeRole.ADMIN:
        return True
    grant = session.scalar(
        select(DeviceAccess.user_id).where(
            DeviceAccess.user_id == user.id,
            DeviceAccess.device_id == device_id,
            *([DeviceAccess.can_control.is_(True)] if control else []),
        )
    )
    return grant is not None


def device_recipients(session: Session, device_id: UUID) -> tuple[UUID | None, set[UUID]]:
    home_id = session.scalar(select(Device.home_id).where(Device.id == device_id))
    if home_id is None:
        return None, set()
    recipients = set(
        session.scalars(
            select(DeviceAccess.user_id).where(DeviceAccess.device_id == device_id)
        )
    )
    recipients.update(
        session.scalars(
            select(HomeMembership.user_id)
            .join(User, User.id == HomeMembership.user_id)
            .where(
                HomeMembership.home_id == home_id,
                HomeMembership.role == HomeRole.ADMIN,
                User.is_active.is_(True),
            )
        )
    )
    return home_id, recipients
