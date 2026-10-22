from collections.abc import Generator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.dependencies import get_db_session
from app.db.models import ActivityLog
from app.db.models import Device
from app.db.models import Sensor
from app.main import app


@pytest.fixture
def client(tmp_path) -> Generator[TestClient, None, None]:
    database_path = tmp_path / "devices.db"
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record) -> None:
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )

    def override_database_session() -> Generator[Session, None, None]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_database_session
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        engine.dispose()


def test_create_list_retrieve_and_update_device(client: TestClient) -> None:
    response = client.post(
        "/devices",
        json={"name": "Hall sensor", "device_type": "temperature", "room": "Hall"},
    )

    assert response.status_code == 201
    created = response.json()
    assert created["name"] == "Hall sensor"
    assert created["status"] == "unknown"
    assert created["online"] is False
    assert created["room"] == "Hall"
    assert created["id"]
    assert created["created_at"]

    listed = client.get("/devices")
    assert listed.status_code == 200
    assert [device["id"] for device in listed.json()] == [created["id"]]

    retrieved = client.get(f"/devices/{created['id']}")
    assert retrieved.status_code == 200
    assert retrieved.json() == created

    updated = client.patch(
        f"/devices/{created['id']}",
        json={"room": None, "online": True, "status": "active"},
    )
    assert updated.status_code == 200
    assert updated.json()["room"] is None
    assert updated.json()["online"] is True
    assert updated.json()["status"] == "active"
    assert updated.json()["name"] == "Hall sensor"


def test_device_create_and_patch_validate_input(client: TestClient) -> None:
    missing_required_field = client.post("/devices", json={"name": "Unnamed"})
    assert missing_required_field.status_code == 422

    empty_name = client.post(
        "/devices",
        json={"name": "  ", "device_type": "temperature"},
    )
    assert empty_name.status_code == 422

    created = client.post(
        "/devices",
        json={"name": "Sensor", "device_type": "temperature"},
    ).json()
    empty_patch = client.patch(f"/devices/{created['id']}", json={})
    null_name = client.patch(f"/devices/{created['id']}", json={"name": None})
    extra_field = client.patch(
        f"/devices/{created['id']}",
        json={"online": True, "unexpected": True},
    )
    assert empty_patch.status_code == 422
    assert null_name.status_code == 422
    assert extra_field.status_code == 422


def test_missing_device_returns_not_found(client: TestClient) -> None:
    device_id = uuid4()
    assert client.get(f"/devices/{device_id}").status_code == 404
    assert (
        client.patch(f"/devices/{device_id}", json={"online": True}).status_code
        == 404
    )
    assert client.delete(f"/devices/{device_id}").status_code == 404


def test_database_errors_return_service_unavailable(
    client: TestClient,
    monkeypatch,
) -> None:
    def fail_commit(_session: Session) -> None:
        raise SQLAlchemyError("database details must not be exposed")

    monkeypatch.setattr(Session, "commit", fail_commit)
    response = client.post(
        "/devices",
        json={"name": "Sensor", "device_type": "temperature"},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Database operation unavailable"}


def test_delete_device_applies_existing_foreign_key_actions(
    client: TestClient,
    tmp_path,
) -> None:
    database_path = tmp_path / "devices.db"
    device_id = uuid4()
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    with Session(engine) as session:
        device = Device(
            id=device_id,
            name="Sensor hub",
            device_type="hub",
        )
        device.sensors.append(
            Sensor(name="Temperature", sensor_type="temperature")
        )
        device.activity_logs.append(
            ActivityLog(source="test", event="device-created")
        )
        session.add(device)
        session.commit()
    engine.dispose()

    response = client.delete(f"/devices/{device_id}")
    assert response.status_code == 204
    assert response.content == b""

    verification_engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    with verification_engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT id FROM devices").all() == []
        assert connection.exec_driver_sql("SELECT id FROM sensors").all() == []
        assert connection.exec_driver_sql(
            "SELECT device_id FROM activity_logs"
        ).scalar_one() is None
    verification_engine.dispose()
