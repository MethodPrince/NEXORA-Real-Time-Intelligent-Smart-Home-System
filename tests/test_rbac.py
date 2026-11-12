from collections.abc import Generator
from uuid import UUID

import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.core.config import get_settings
from app.db.dependencies import get_db_session
from app.db.models import User
from app.db.models import UserRole
from app.db.models import ActivityLog
from app.db.models import AutomationRule
from app.db.models import Device
from app.db.models import DeviceAccess
from app.db.models import Home
from app.db.models import HomeMembership
from app.db.models import SecurityEvent
from app.db.models import Sensor
from app.main import app
from app.services.bootstrap import create_first_admin
from app.services.auth import create_access_token
from app.services.auth import hash_password


@pytest.fixture
def rbac_context(tmp_path) -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
    engine = create_engine(f"sqlite:///{(tmp_path / 'rbac.db').as_posix()}")
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


def create_admin(client: TestClient, factory: sessionmaker[Session]) -> User:
    with factory() as session:
        admin = create_first_admin(
            session,
            name="System Admin",
            email="admin@example.com",
            password="a secure admin password",
        )
        admin_id = admin.id
    login = client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": "a secure admin password"},
    )
    assert login.status_code == 200
    client.headers.update({"Authorization": f"Bearer {login.json()['access_token']}"})
    with factory() as session:
        saved = session.get(User, admin_id)
        assert saved is not None
        membership = session.query(HomeMembership).filter_by(user_id=admin_id).one()
        client.headers.update({"X-Home-ID": str(membership.home_id)})
        return saved


def login_as(client: TestClient, email: str, password: str) -> dict[str, object]:
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    client.headers.update({"Authorization": f"Bearer {response.json()['access_token']}"})
    user = response.json()["user"]
    memberships = client.get("/homes").json()
    if memberships:
        user["role"] = memberships[0]["role"]
    return user


def test_public_registration_cannot_create_an_admin(rbac_context) -> None:
    client, _factory = rbac_context
    response = client.post(
        "/auth/register",
        json={
            "name": "Public",
            "email": "public@example.com",
            "password": "a sufficiently long password",
            "role": "ADMIN",
        },
    )
    assert response.status_code == 422
    created = client.post(
        "/auth/register",
        json={
            "name": "Public",
            "email": "public@example.com",
            "password": "a sufficiently long password",
        },
    )
    assert created.status_code == 201
    assert created.json()["user"]["role"] == "STANDARD_USER"


def test_first_admin_bootstrap_is_one_time_and_password_hashed(rbac_context) -> None:
    _client, factory = rbac_context
    with factory() as session:
        admin = create_first_admin(
            session,
            name="First Admin",
            email="first@example.com",
            password="a secure bootstrap password",
        )
        assert admin.role == UserRole.ADMIN
        assert admin.password_hash != "a secure bootstrap password"
        with pytest.raises(ValueError, match="already exists"):
            create_first_admin(
                session,
                name="Second Admin",
                email="second@example.com",
                password="another secure password",
            )


def test_admin_user_management_and_last_admin_protection(rbac_context) -> None:
    client, factory = rbac_context
    admin = create_admin(client, factory)
    created = client.post(
        "/admin/users",
        json={
            "name": "Guest Example",
            "email": "guest@example.com",
            "password": "a sufficiently long password",
            "role": "GUEST",
        },
    )
    assert created.status_code == 201
    guest_id = created.json()["id"]
    assert created.json()["is_active"] is True
    home_admin = client.post(
        "/admin/users",
        json={
            "name": "Unapproved Admin",
            "email": "unapproved@example.com",
            "password": "a sufficiently long password",
            "role": "ADMIN",
        },
    )
    assert home_admin.status_code == 201
    home_admin_id = home_admin.json()["id"]
    assert client.get("/admin/users").status_code == 200
    assert client.patch(
        f"/admin/users/{admin.id}",
        json={"is_active": False},
    ).status_code == 409
    assert client.patch(
        f"/admin/users/{guest_id}",
        json={"is_active": False},
    ).json()["is_active"] is False
    assert client.patch(
        f"/admin/users/{home_admin_id}",
        json={"is_active": False},
    ).json()["is_active"] is False
    login = client.post(
        "/auth/login",
        json={"email": "guest@example.com", "password": "a sufficiently long password"},
    )
    assert login.status_code == 200
    client.headers.update({"Authorization": f"Bearer {login.json()['access_token']}"})
    assert client.get("/homes").json() == []
    assert client.get("/devices").status_code == 404


def test_admin_controls_registration_and_standard_users_cannot(rbac_context) -> None:
    client, factory = rbac_context
    create_admin(client, factory)
    guest = client.post(
        "/admin/users",
        json={
            "name": "Standard",
            "email": "standard@example.com",
            "password": "a sufficiently long password",
        },
    )
    assert guest.status_code == 201
    assert client.patch(
        "/admin/security-settings",
        json={"registration_enabled": False},
    ).json()["registration_enabled"] is False
    assert client.post(
        "/auth/register",
        json={
            "name": "Blocked",
            "email": "blocked@example.com",
            "password": "a sufficiently long password",
        },
    ).status_code == 403

    home_admin = client.post(
        "/admin/users",
        json={
            "name": "Home Admin",
            "email": "home-admin@example.com",
            "password": "a sufficiently long password",
            "role": "ADMIN",
        },
    )
    assert home_admin.status_code == 201
    login_as(client, "home-admin@example.com", "a sufficiently long password")
    assert client.get("/admin/security-settings").status_code == 403
    assert client.patch(
        "/admin/security-settings",
        json={"registration_enabled": True},
    ).status_code == 403

    login_as(client, "standard@example.com", "a sufficiently long password")
    assert client.patch(
        "/admin/security-settings",
        json={"registration_enabled": True},
    ).status_code == 403


def test_admin_can_delete_selected_home_and_its_data_but_not_last_home(rbac_context) -> None:
    client, factory = rbac_context
    admin = create_admin(client, factory)
    original_home_id = UUID(client.headers["X-Home-ID"])
    created_home = client.post("/homes", json={"name": "Second Home"})
    assert created_home.status_code == 201
    home_id = UUID(created_home.json()["id"])

    assert client.delete(f"/homes/{home_id}").status_code == 404
    client.headers.update({"X-Home-ID": str(home_id)})
    member_response = client.post(
        "/admin/users",
        json={
            "name": "Family Member",
            "email": "family@example.com",
            "password": "a sufficiently long password",
            "role": "STANDARD_USER",
        },
    )
    assert member_response.status_code == 201
    member_id = UUID(member_response.json()["id"])

    with factory() as session:
        device = Device(
            home_id=home_id,
            name="Second Home Lamp",
            device_type="smart_light",
        )
        session.add(device)
        session.flush()
        session.add_all(
            [
                Sensor(
                    name="Temperature",
                    sensor_type="temperature",
                    device_id=device.id,
                ),
                DeviceAccess(user_id=member_id, device_id=device.id),
                AutomationRule(home_id=home_id, name="Evening lights"),
                ActivityLog(
                    home_id=home_id,
                    user_id=member_id,
                    device_id=device.id,
                    source="test",
                    event="device_created",
                ),
            ]
        )
        session.commit()
        device_id = device.id

    deleted = client.delete(f"/homes/{home_id}")
    assert deleted.status_code == 204
    assert client.get("/homes").json() == [
        {"id": str(original_home_id), "name": "NEXORA Home", "role": "ADMIN"}
    ]

    with factory() as session:
        assert session.get(Home, home_id) is None
        assert session.get(Device, device_id) is None
        assert session.query(Sensor).filter_by(device_id=device_id).count() == 0
        assert session.query(DeviceAccess).filter_by(device_id=device_id).count() == 0
        assert session.query(AutomationRule).filter_by(home_id=home_id).count() == 0
        assert session.query(ActivityLog).filter_by(home_id=home_id).count() == 0
        assert session.get(User, member_id) is not None
        assert session.query(HomeMembership).filter_by(home_id=home_id).count() == 0
        deletion_event = (
            session.query(SecurityEvent)
            .filter_by(event_type="home_deleted", user_id=admin.id)
            .one()
        )
        assert deletion_event.home_id is None
        assert deletion_event.metadata_json["home_id"] == str(home_id)
        assert deletion_event.metadata_json["home_name"] == "Second Home"

    client.headers.update({"X-Home-ID": str(original_home_id)})
    assert client.delete(f"/homes/{original_home_id}").status_code == 409


def test_standard_user_device_grants_guest_restrictions_and_admin_scope(rbac_context) -> None:
    client, factory = rbac_context
    create_admin(client, factory)
    first_device = client.post(
        "/devices",
        json={"name": "Hall light", "device_type": "smart_light", "simulated": True},
    ).json()
    second_device = client.post(
        "/devices",
        json={"name": "Bedroom fan", "device_type": "smart_fan", "simulated": True},
    ).json()
    standard_response = client.post(
        "/admin/users",
        json={
            "name": "Standard",
            "email": "standard@example.com",
            "password": "a sufficiently long password",
        },
    )
    guest_response = client.post(
        "/admin/users",
        json={
            "name": "Guest",
            "email": "guest@example.com",
            "password": "a sufficiently long password",
            "role": "GUEST",
        },
    )
    assert standard_response.status_code == guest_response.status_code == 201
    standard_id = standard_response.json()["id"]
    guest_id = guest_response.json()["id"]
    assert client.put(
        f"/admin/users/{standard_id}/device-access",
        json={"grants": [{"device_id": first_device["id"], "can_control": True}]},
    ).status_code == 200
    assert client.put(
        f"/admin/users/{guest_id}/device-access",
        json={"grants": [{"device_id": first_device["id"], "can_control": False}]},
    ).status_code == 200

    standard = login_as(client, "standard@example.com", "a sufficiently long password")
    assert standard["role"] == "STANDARD_USER"
    assert [device["id"] for device in client.get("/devices").json()] == [first_device["id"]]
    assert client.post(
        "/devices",
        json={"name": "Unapproved", "device_type": "light"},
    ).status_code == 403
    assert client.patch(f"/devices/{first_device['id']}", json={"name": "Renamed"}).status_code == 403
    assert client.post(
        f"/devices/{first_device['id']}/command",
        json={"command": "set_power", "parameters": {"enabled": True}},
    ).status_code == 202
    assert client.get(f"/devices/{second_device['id']}").status_code == 404

    guest = login_as(client, "guest@example.com", "a sufficiently long password")
    assert guest["role"] == "GUEST"
    assert [device["id"] for device in client.get("/devices").json()] == [first_device["id"]]
    assert client.get(f"/devices/{first_device['id']}").status_code == 200
    assert client.post(
        f"/devices/{first_device['id']}/command",
        json={"command": "set_power", "parameters": {"enabled": True}},
    ).status_code == 404
    assert client.get("/automations").status_code == 403
    assert client.get("/activity").status_code == 403
    assert client.get("/admin/users").status_code == 403


def test_admin_endpoints_require_auth_and_inactive_websocket_is_rejected(rbac_context) -> None:
    client, factory = rbac_context
    admin = create_admin(client, factory)
    token = client.headers["Authorization"].removeprefix("Bearer ")
    with factory() as session:
        user = User(
            name="Inactive",
            email="inactive@example.com",
            password_hash=hash_password("a sufficiently long password"),
            role=UserRole.STANDARD_USER,
            is_active=False,
        )
        session.add(user)
        session.commit()
        inactive_id = user.id
    inactive_token = client.post(
        "/auth/login",
        json={"email": "inactive@example.com", "password": "a sufficiently long password"},
    )
    assert inactive_token.status_code == 401
    assert client.get(
        "/admin/users",
        headers={"Authorization": "Bearer invalid"},
    ).status_code == 401
    assert client.get("/admin/users", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    invalidated_token, _ = create_access_token(inactive_id, get_settings())
    with pytest.raises(WebSocketDisconnect) as error:
        with client.websocket_connect(
            "/ws",
            subprotocols=["nexora", f"bearer.{invalidated_token}"],
            headers={"origin": "http://localhost:5173"},
        ):
            pass
    assert error.value.code == 4401
