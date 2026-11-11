from collections.abc import Generator
from uuid import UUID

import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.dependencies import get_db_session
from app.db.models import Device
from app.db.models import ActivityLog
from app.db.models import Home
from app.db.models import HomeMembership
from app.db.models import HomeRole
from app.db.models import SecurityEvent
from app.db.models import Sensor
from app.db.models import User
from app.main import app
from app.services.bootstrap import create_first_admin


@pytest.fixture
def multi_home_context(
    tmp_path,
) -> Generator[tuple[TestClient, sessionmaker[Session], UUID, UUID, UUID, UUID, str], None, None]:
    engine = create_engine(f"sqlite:///{(tmp_path / 'multi-home.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_session():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    try:
        with factory() as session:
            admin = create_first_admin(
                session,
                name="Home A Admin",
                email="home-a@example.com",
                password="a sufficiently long password",
            )
            admin_id = admin.id
            home_a_id = admin.home_memberships[0].home_id

        with TestClient(app) as client:
            login = client.post(
                "/auth/login",
                json={
                    "email": "home-a@example.com",
                    "password": "a sufficiently long password",
                },
            )
            assert login.status_code == 200
            admin_token = login.json()["access_token"]
            client.headers.update({"Authorization": f"Bearer {admin_token}"})
            client.headers.update({"X-Home-ID": str(home_a_id)})

            registered = client.post(
                "/auth/register",
                json={
                    "name": "Home B Admin",
                    "email": "home-b@example.com",
                    "password": "another sufficiently long password",
                },
            )
            assert registered.status_code == 201
            home_b_user_id = UUID(registered.json()["user"]["id"])

            with factory() as session:
                home_b = Home(name="Home B")
                session.add(home_b)
                session.flush()
                session.add(
                    HomeMembership(
                        user_id=home_b_user_id,
                        home_id=home_b.id,
                        role=HomeRole.ADMIN,
                    )
                )
                device = Device(
                    home_id=home_b.id,
                    owner_user_id=home_b_user_id,
                    name="Private Home B light",
                    device_type="smart_light",
                )
                device.sensors.append(
                    Sensor(
                        name="Home B temperature",
                        sensor_type="temperature",
                        reading=22.0,
                    )
                )
                session.add(device)
                session.add(
                    ActivityLog(
                        home_id=home_b.id,
                        user_id=home_b_user_id,
                        device_id=device.id,
                        source="test",
                        event="home-b-event",
                    )
                )
                session.commit()
                home_b_id = home_b.id
                device_id = device.id

            client.headers.update({"Authorization": f"Bearer {admin_token}"})
            yield (
                client,
                factory,
                home_a_id,
                home_b_id,
                home_b_user_id,
                device_id,
                admin_token,
            )
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        engine.dispose()


def test_home_access_admin_management_and_websocket_are_isolated(
    multi_home_context,
) -> None:
    (
        client,
        factory,
        home_a_id,
        home_b_id,
        home_b_user_id,
        device_id,
        admin_token,
    ) = multi_home_context

    client.headers.update({"X-Home-ID": str(home_b_id)})
    assert client.get("/devices").status_code == 404
    client.headers.update({"X-Home-ID": str(home_a_id)})
    assert client.patch(
        f"/admin/users/{home_b_user_id}",
        json={"is_active": False},
    ).status_code == 404

    client.headers.update({"X-Home-ID": str(home_b_id)})
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            f"/ws?home_id={home_b_id}",
            subprotocols=["nexora", f"bearer.{admin_token}"],
            headers={"origin": "http://localhost:5173"},
        ):
            pass

    home_b_login = client.post(
        "/auth/login",
        json={
            "email": "home-b@example.com",
            "password": "another sufficiently long password",
        },
    )
    assert home_b_login.status_code == 200
    client.headers.update(
        {"Authorization": f"Bearer {home_b_login.json()['access_token']}"}
    )
    home_b_headers = {"X-Home-ID": str(home_b_id)}
    assert [
        row["id"] for row in client.get("/devices", headers=home_b_headers).json()
    ] == [str(device_id)]
    assert client.get("/sensors", headers=home_b_headers).json()[0]["name"] == "Home B temperature"
    assert client.get("/activity", headers=home_b_headers).json()[0]["event"] == "home-b-event"
    automation = client.post(
        "/automations",
        headers=home_b_headers,
        json={
            "name": "Home B schedule",
            "trigger": {
                "type": "schedule",
                "time": "07:30",
                "timezone": "UTC",
                "days": [0],
            },
            "action": {"device_id": str(device_id), "command": "turn_on"},
        },
    )
    assert automation.status_code == 201, automation.text
    home_a_headers = {"X-Home-ID": str(home_a_id)}
    assert client.get("/devices", headers=home_a_headers).status_code == 404
    assert client.get("/sensors", headers=home_a_headers).status_code == 404
    assert client.get("/activity", headers=home_a_headers).status_code == 404
    assert client.get("/automations", headers=home_a_headers).status_code == 404

    failed_login = client.post(
        "/auth/login",
        json={"email": "unknown@example.com", "password": "unmatched password"},
    )
    assert failed_login.status_code == 401
    client.headers.update({"Authorization": f"Bearer {admin_token}"})
    client.headers.update(home_a_headers)
    listed_events = client.get("/admin/security-events")
    assert listed_events.status_code == 200
    assert any(
        event["event_type"] == "login_succeeded"
        for event in listed_events.json()
    )
    assert any(event["event_type"] == "login_failed" for event in listed_events.json())

    with factory() as session:
        events = list(
            session.scalars(
                select(SecurityEvent).where(
                    SecurityEvent.event_type.in_(
                        ["home_access_denied", "access_denied", "websocket_authentication_failed"]
                    )
                )
            )
        )
    event_types = {event.event_type for event in events}
    assert {
        "home_access_denied",
        "access_denied",
        "websocket_authentication_failed",
    } <= event_types
    assert all(event.source_ip for event in events)
    assert all(
        "another sufficiently long password" not in str(event.metadata_json)
        and admin_token not in str(event.metadata_json)
        for event in events
    )
