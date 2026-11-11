from collections.abc import Generator
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from uuid import UUID
from uuid import uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.core.config import get_settings
from app.db.base import Base
from app.db.dependencies import get_db_session
from app.db.models import ActivityLog
from app.db.models import Device
from app.db.models import DeviceAccess
from app.db.models import Sensor
from app.db.models import HomeMembership
from app.db.models import HomeRole
from app.db.models import SecurityEvent
from app.db.models import User
from app.main import app
from app.services.auth import verify_password
from tests.auth_helpers import make_current_user_admin
from tests.auth_helpers import register_user


@pytest.fixture
def auth_context(tmp_path) -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
    engine = create_engine(f"sqlite:///{(tmp_path / 'auth.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_session():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    try:
        with TestClient(app) as client:
            yield client, factory
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        engine.dispose()


def test_registration_hashes_password_and_login_returns_expiring_jwt(auth_context) -> None:
    client, factory = auth_context
    registered = client.post(
        "/auth/register",
        json={
            "name": "  Ada  ",
            "email": " ADA@example.com ",
            "password": "eight888",
        },
    )
    assert registered.status_code == 201
    token_data = registered.json()
    assert token_data["token_type"] == "bearer"
    assert token_data["expires_in"] == 1800
    assert token_data["user"]["email"] == "ada@example.com"
    with factory() as session:
        user = session.get(User, UUID(token_data["user"]["id"]))
        assert user is not None
        assert user.role.value == "STANDARD_USER"
        assert user.password_hash != "eight888"
        assert verify_password("eight888", user.password_hash)
        assert user.home_memberships == []

    login = client.post(
        "/auth/login",
        json={"email": "ADA@example.com", "password": "eight888"},
    )
    assert login.status_code == 200
    client.headers.update({"Authorization": f"Bearer {login.json()['access_token']}"})
    assert client.get("/auth/me").json()["email"] == "ada@example.com"


def test_registration_rejects_duplicate_and_weak_password(auth_context) -> None:
    client, _factory = auth_context
    _token, _user_id = register_user(client)
    duplicate = client.post(
        "/auth/register",
        json={
            "name": "Another",
            "email": "owner@example.com",
            "password": "correct horse battery staple",
        },
    )
    weak_password = client.post(
        "/auth/register",
        json={"name": "Weak", "email": "weak@example.test", "password": "short77"},
    )
    invalid_email = client.post(
        "/auth/register",
        json={
            "name": "Invalid",
            "email": "not-an-email",
            "password": "correct horse battery staple",
        },
    )
    assert duplicate.status_code == 409
    assert weak_password.status_code == 422
    assert invalid_email.status_code == 422


def test_login_uses_same_error_for_unknown_user_and_wrong_password(auth_context) -> None:
    client, factory = auth_context
    register_user(client)
    unknown = client.post(
        "/auth/login",
        json={"email": "unknown@example.com", "password": "correct horse battery staple"},
    )
    wrong = client.post(
        "/auth/login",
        json={"email": "owner@example.com", "password": "wrong password"},
    )
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json() == {"detail": "Invalid email or password"}
    successful = client.post(
        "/auth/login",
        json={"email": "owner@example.com", "password": "correct horse battery staple"},
    )
    assert successful.status_code == 200
    with factory() as session:
        events = list(
            session.scalars(
                select(SecurityEvent).where(
                    SecurityEvent.event_type.in_(["login_failed", "login_succeeded"])
                )
            )
        )
    assert [event.outcome for event in events].count("failure") == 2
    assert [event.outcome for event in events].count("success") == 1
    assert all(event.timestamp is not None for event in events)
    assert all(event.source_ip for event in events)
    assert all(
        "correct horse battery staple" not in str(event.metadata_json)
        and successful.json()["access_token"] not in str(event.metadata_json)
        for event in events
    )


def test_private_endpoints_require_bearer_authentication(auth_context) -> None:
    client, _factory = auth_context
    protected_requests = [
        ("GET", "/devices"),
        ("GET", "/automations"),
        ("GET", "/sensors"),
        ("GET", "/activity"),
        ("POST", "/events/test"),
        ("POST", f"/devices/{uuid4()}/command"),
        ("PATCH", f"/devices/{uuid4()}"),
        ("DELETE", f"/devices/{uuid4()}"),
    ]
    for method, path in protected_requests:
        response = client.request(method, path, json={})
        assert response.status_code == 401, path
    assert client.get("/auth/me").status_code == 401


def test_expired_and_wrong_audience_tokens_are_rejected(auth_context) -> None:
    client, _factory = auth_context
    expired = jwt.encode(
        {
            "sub": str(uuid4()),
            "iat": datetime.now(UTC) - timedelta(hours=1),
            "exp": datetime.now(UTC) - timedelta(minutes=1),
            "iss": "nexora",
            "aud": "nexora-api",
            "type": "access",
            "jti": str(uuid4()),
        },
        get_settings().jwt_secret_key,
        algorithm="HS256",
    )
    wrong_audience = jwt.encode(
        {
            "sub": str(uuid4()),
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(minutes=1),
            "iss": "nexora",
            "aud": "other-api",
            "type": "access",
            "jti": str(uuid4()),
        },
        get_settings().jwt_secret_key,
        algorithm="HS256",
    )
    for token in (expired, wrong_audience, "not-a-jwt"):
        client.headers.update({"Authorization": f"Bearer {token}"})
        assert client.get("/auth/me").status_code == 401


def test_users_cannot_access_other_users_devices_or_automations(auth_context) -> None:
    client, factory = auth_context
    _owner_token, _owner_id = register_user(client)
    make_current_user_admin(client, factory)
    device = client.post(
        "/devices",
        json={"name": "Private light", "device_type": "smart_light", "simulated": True},
    ).json()
    rule = client.post(
        "/automations",
        json={
            "name": "Private schedule",
            "trigger": {
                "type": "schedule",
                "time": "07:30",
                "timezone": "UTC",
                "days": [0],
            },
            "action": {"device_id": device["id"], "command": "turn_on"},
        },
    ).json()

    other_token, _other_id = register_user(
        client,
        email="other@example.com",
        name="Other User",
    )
    with factory() as session:
        session.add(
            HomeMembership(
                user_id=_other_id,
                home_id=UUID(client.headers["X-Home-ID"]),
                role=HomeRole.STANDARD_USER,
            )
        )
        session.commit()
    client.headers.update({"Authorization": f"Bearer {other_token}"})
    assert client.get("/devices").json() == []
    assert client.get("/automations").json() == []
    assert client.get(f"/devices/{device['id']}").status_code == 404
    assert client.patch(f"/devices/{device['id']}", json={"name": "Stolen"}).status_code == 403
    assert client.delete(f"/devices/{device['id']}").status_code == 403
    assert client.post(
        f"/devices/{device['id']}/command",
        json={"command": "set_power", "parameters": {"enabled": True}},
    ).status_code == 404
    assert client.patch(f"/automations/{rule['id']}", json={"enabled": False}).status_code == 404
    assert client.delete(f"/automations/{rule['id']}").status_code == 404
    cross_user_automation = client.post(
        "/automations",
        json={
            "name": "Invalid cross-user schedule",
            "trigger": {
                "type": "schedule",
                "time": "07:30",
                "timezone": "UTC",
                "days": [0],
            },
            "action": {"device_id": device["id"], "command": "turn_on"},
        },
    )
    assert cross_user_automation.status_code == 404


def test_sensors_and_activity_are_scoped_to_owner(auth_context) -> None:
    client, factory = auth_context
    _token, owner_id = register_user(client)
    make_current_user_admin(client, factory)
    _other_token, other_id = register_user(
        client,
        email="other@example.com",
        name="Other User",
    )
    home_id = UUID(client.headers["X-Home-ID"])
    with factory() as session:
        session.add(
            HomeMembership(
                user_id=other_id,
                home_id=home_id,
                role=HomeRole.STANDARD_USER,
            )
        )
        owner_membership = session.get(
            HomeMembership,
            {"user_id": owner_id, "home_id": home_id},
        )
        assert owner_membership is not None
        owner_membership.role = HomeRole.STANDARD_USER
        owner_device = Device(
            home_id=home_id,
            owner_user_id=owner_id,
            name="Owner sensor hub",
            device_type="sensor",
        )
        other_device = Device(
            home_id=home_id,
            owner_user_id=other_id,
            name="Other sensor hub",
            device_type="sensor",
        )
        session.add_all([owner_device, other_device])
        session.flush()
        session.add_all(
            [
                DeviceAccess(user_id=owner_id, device_id=owner_device.id, can_control=True),
                DeviceAccess(user_id=other_id, device_id=other_device.id, can_control=True),
                Sensor(
                    device_id=owner_device.id,
                    name="Owner temperature",
                    sensor_type="temperature",
                    reading=20.0,
                ),
                Sensor(
                    device_id=other_device.id,
                    name="Other temperature",
                    sensor_type="temperature",
                    reading=30.0,
                ),
                ActivityLog(
                    home_id=home_id,
                    user_id=owner_id,
                    device_id=owner_device.id,
                    source="test",
                    event="owner-event",
                ),
                ActivityLog(
                    home_id=home_id,
                    user_id=other_id,
                    device_id=other_device.id,
                    source="test",
                    event="other-event",
                ),
            ]
        )
        session.commit()

    client.headers.update({"Authorization": f"Bearer {_token}"})
    client.headers.update({"Authorization": f"Bearer {_token}"})
    assert [row["name"] for row in client.get("/sensors").json()] == ["Owner temperature"]
    assert [row["event"] for row in client.get("/activity").json()] == ["owner-event"]


def test_registration_fails_closed_without_jwt_secret(auth_context, monkeypatch) -> None:
    client, _factory = auth_context
    monkeypatch.setattr(
        "app.api.routes.auth.get_settings",
        lambda: Settings(jwt_secret_key=None),
    )
    response = client.post(
        "/auth/register",
        json={
            "name": "No secret",
            "email": "no-secret@example.com",
            "password": "correct horse battery staple",
        },
    )
    assert response.status_code == 503
    assert response.json() == {"detail": "Authentication is not configured"}
