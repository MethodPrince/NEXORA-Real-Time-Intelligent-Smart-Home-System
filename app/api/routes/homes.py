import logging

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.schemas.homes import HomeCreate
from app.api.schemas.homes import HomeRead
from app.db.dependencies import HomeAccess
from app.db.dependencies import get_current_user
from app.db.dependencies import get_db_session
from app.db.dependencies import require_admin
from app.db.models import Home
from app.db.models import HomeMembership
from app.db.models import User
from app.services.security_events import add_security_event

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
