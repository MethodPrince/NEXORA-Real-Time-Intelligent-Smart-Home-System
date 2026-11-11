from fastapi.testclient import TestClient
from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker

from app.db.models import User
from app.db.models import UserRole
from app.db.models import Home
from app.db.models import HomeMembership
from app.db.models import HomeRole


def register_user(
    client: TestClient,
    email: str = "owner@example.com",
    name: str = "Home Owner",
) -> tuple[str, UUID]:
    response = client.post(
        "/auth/register",
        json={
            "name": name,
            "email": email,
            "password": "correct horse battery staple",
        },
    )
    assert response.status_code == 201, response.text
    token = response.json()["access_token"]
    client.headers.update({"Authorization": f"Bearer {token}"})
    return token, UUID(response.json()["user"]["id"])


def make_current_user_admin(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    user_id = UUID(client.get("/auth/me").json()["id"])
    with session_factory() as session:
        user = session.get(User, user_id)
        assert user is not None
        user.role = UserRole.ADMIN
        home = Home(name="Test Home")
        session.add(home)
        session.flush()
        session.add(
            HomeMembership(
                user_id=user.id,
                home_id=home.id,
                role=HomeRole.ADMIN,
            )
        )
        session.commit()
        client.headers.update({"X-Home-ID": str(home.id)})
