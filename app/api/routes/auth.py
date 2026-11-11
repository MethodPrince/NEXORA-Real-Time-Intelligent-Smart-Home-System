import logging

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Request
from fastapi import Response
from fastapi import status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.schemas.auth import LoginRequest
from app.api.schemas.auth import RegisterRequest
from app.api.schemas.auth import TokenResponse
from app.api.schemas.auth import UserRead
from app.core.config import get_settings
from app.db.dependencies import get_current_user
from app.db.dependencies import get_db_session
from app.db.models import User
from app.db.models import UserRole
from app.db.models import SystemSettings
from app.services.auth import create_access_token
from app.services.auth import hash_password
from app.services.auth import verify_password
from app.services.auth import verify_unknown_user_password
from app.services.security_events import add_security_event
from app.services.security_events import record_security_event

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["authentication"])


def _issue_token(user: User, response: Response) -> TokenResponse:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    try:
        token, expires_in = create_access_token(user.id, get_settings())
    except RuntimeError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured",
        ) from error
    return TokenResponse(
        access_token=token,
        expires_in=expires_in,
        user=UserRead.model_validate(user),
    )


@router.post("/register", response_model=TokenResponse, status_code=201)
def register(
    request: RegisterRequest,
    http_request: Request,
    response: Response,
    session: Session = Depends(get_db_session),
) -> TokenResponse:
    if not get_settings().jwt_secret_key:
        raise HTTPException(
            status_code=503,
            detail="Authentication is not configured",
        )
    security_settings = session.get(SystemSettings, 1)
    if security_settings is not None and not security_settings.registration_enabled:
        raise HTTPException(status_code=403, detail="Public registration is disabled")
    user = User(
        name=request.name,
        email=str(request.email),
        password_hash=hash_password(request.password),
        role=UserRole.STANDARD_USER,
    )
    try:
        session.add(user)
        session.flush()
        add_security_event(
            session,
            event_type="user_registered",
            severity="info",
            source="/auth/register",
            outcome="success",
            user_id=user.id,
            request=http_request,
            metadata={"method": "POST"},
        )
        session.commit()
        session.refresh(user)
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        ) from error
    except SQLAlchemyError as error:
        session.rollback()
        logger.exception("User registration failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Account service unavailable",
        ) from error
    return _issue_token(user, response)


@router.post("/login", response_model=TokenResponse)
def login(
    request: LoginRequest,
    http_request: Request,
    response: Response,
    session: Session = Depends(get_db_session),
) -> TokenResponse:
    if not get_settings().jwt_secret_key:
        raise HTTPException(
            status_code=503,
            detail="Authentication is not configured",
        )
    user = session.scalar(select(User).where(User.email == str(request.email)))
    password_matches = (
        verify_password(request.password, user.password_hash)
        if user is not None
        else False
    )
    if user is None:
        verify_unknown_user_password(request.password)
    if not password_matches:
        record_security_event(
            session,
            event_type="login_failed",
            severity="warning",
            source="/auth/login",
            outcome="failure",
            user_id=user.id if user is not None else None,
            request=http_request,
            metadata={"reason": "invalid_credentials"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        record_security_event(
            session,
            event_type="login_failed",
            severity="warning",
            source="/auth/login",
            outcome="failure",
            user_id=user.id,
            request=http_request,
            metadata={"reason": "inactive_account"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    record_security_event(
        session,
        event_type="login_succeeded",
        severity="info",
        source="/auth/login",
        outcome="success",
        user_id=user.id,
        request=http_request,
        metadata={"method": "password"},
    )
    return _issue_token(user, response)


@router.get("/me", response_model=UserRead)
def read_current_user(
    user: User = Depends(get_current_user),
) -> UserRead:
    return UserRead.model_validate(user)
