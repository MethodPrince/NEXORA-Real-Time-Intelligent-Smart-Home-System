from sqlalchemy import select
from sqlalchemy.orm import Session
from pydantic import EmailStr
from pydantic import TypeAdapter

from app.db.models import Home
from app.db.models import HomeMembership
from app.db.models import HomeRole
from app.db.models import User
from app.db.models import UserRole
from app.services.auth import hash_password


def create_first_admin(
    session: Session,
    *,
    name: str,
    email: str,
    password: str,
) -> User:
    normalized_name = name.strip()
    normalized_email = str(TypeAdapter(EmailStr).validate_python(email)).lower()
    if not normalized_name:
        raise ValueError("Administrator name is required")
    if len(password) < 8:
        raise ValueError("Password must contain at least 8 characters")
    if session.scalar(select(HomeMembership.user_id).where(
        HomeMembership.role == HomeRole.ADMIN
    )) is not None:
        raise ValueError("An administrator account already exists")
    user = User(
        name=normalized_name,
        email=normalized_email,
        password_hash=hash_password(password),
        role=UserRole.ADMIN,
        is_active=True,
    )
    home = Home(name="NEXORA Home")
    session.add_all(
        [
            user,
            home,
        ]
    )
    session.flush()
    session.add(
        HomeMembership(
            user_id=user.id,
            home_id=home.id,
            role=HomeRole.ADMIN,
        )
    )
    session.commit()
    session.refresh(user)
    return user
