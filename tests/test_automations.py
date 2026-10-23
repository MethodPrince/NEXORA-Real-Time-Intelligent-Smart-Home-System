from collections.abc import Generator
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.db.base import Base
from app.db.dependencies import get_db_session
from app.db.models import AutomationRule
from app.db.models import Device
from app.main import app
from app.services.automation_scheduler import AutomationScheduler
from app.services.automation_scheduler import next_run_time
from app.services.mqtt import MQTTService
from app.services.simulator import simulated_state


@pytest.fixture
def automation_db(tmp_path) -> Generator[sessionmaker[Session], None, None]:
    engine = create_engine(f"sqlite:///{(tmp_path / 'automations.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_database_session() -> Generator[Session, None, None]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_database_session
    try:
        yield factory
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        engine.dispose()


@pytest.fixture
def client(automation_db) -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client


def create_simulated_light(client: TestClient) -> str:
    response = client.post(
        "/devices",
        json={
            "name": "Bedroom light",
            "room": "Bedroom",
            "device_type": "smart_light",
            "simulated": True,
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_scheduled_automation_crud(client: TestClient) -> None:
    device_id = create_simulated_light(client)
    payload = {
        "name": "Wake up lights",
        "trigger": {
            "type": "schedule",
            "time": "07:30",
            "timezone": "Europe/Paris",
            "days": [0, 1, 2, 3, 4],
        },
        "action": {"device_id": device_id, "command": "turn_on"},
    }

    created = client.post("/automations", json=payload)
    assert created.status_code == 201
    rule = created.json()
    assert rule["enabled"] is True
    assert rule["trigger"]["days"] == [0, 1, 2, 3, 4]
    assert rule["action"]["device_id"] == device_id
    assert rule["next_run_at"]

    listed = client.get("/automations")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [rule["id"]]

    paused = client.patch(f"/automations/{rule['id']}", json={"enabled": False})
    assert paused.status_code == 200
    assert paused.json()["enabled"] is False
    assert paused.json()["next_run_at"] is None

    resumed = client.patch(f"/automations/{rule['id']}", json={"enabled": True})
    assert resumed.status_code == 200
    assert resumed.json()["next_run_at"]

    removed = client.delete(f"/automations/{rule['id']}")
    assert removed.status_code == 204
    assert client.get("/automations").json() == []


def test_scheduled_automation_validates_schedule_and_device(client: TestClient) -> None:
    device_id = create_simulated_light(client)
    invalid_schedule = client.post(
        "/automations",
        json={
            "name": "Bad schedule",
            "trigger": {
                "type": "schedule",
                "time": "25:00",
                "timezone": "Not/AZone",
                "days": [7],
            },
            "action": {"device_id": device_id, "command": "turn_on"},
        },
    )
    missing_device = client.post(
        "/automations",
        json={
            "name": "Missing device",
            "trigger": {
                "type": "schedule",
                "time": "07:30",
                "timezone": "UTC",
                "days": [0],
            },
            "action": {"device_id": str(uuid4()), "command": "turn_on"},
        },
    )
    invalid_action = client.post(
        "/automations",
        json={
            "name": "Wrong action",
            "trigger": {
                "type": "schedule",
                "time": "07:30",
                "timezone": "UTC",
                "days": [0],
            },
            "action": {"device_id": device_id, "command": "open"},
        },
    )

    assert invalid_schedule.status_code == 422
    assert missing_device.status_code == 404
    assert invalid_action.status_code == 422


def test_next_run_time_uses_configured_timezone() -> None:
    now = datetime(2026, 10, 23, 6, 0, tzinfo=UTC)
    scheduled = next_run_time(
        {
            "time": "09:30",
            "timezone": "Europe/Paris",
            "days": [4],
        },
        now,
    )

    assert scheduled.astimezone(ZoneInfo("Europe/Paris")).hour == 9
    assert scheduled.astimezone(ZoneInfo("Europe/Paris")).minute == 30
    assert scheduled > now


def test_scheduler_runs_due_simulated_device_action(automation_db) -> None:
    factory = automation_db
    due = datetime.now(UTC) - timedelta(minutes=1)
    device = Device(
        id=uuid4(),
        name="Scheduled light",
        room="Office",
        device_type="smart_light",
        status="simulator:{\"power\":false,\"brightness\":100}",
        online=True,
    )
    rule = AutomationRule(
        name="Turn on office light",
        trigger_conditions={
            "type": "schedule",
            "time": "07:30",
            "timezone": "UTC",
            "days": [0, 1, 2, 3, 4, 5, 6],
        },
        actions=[{"device_id": str(device.id), "command": "turn_on"}],
        enabled=True,
        next_run_at=due,
    )
    with factory() as session:
        session.add_all([device, rule])
        session.commit()

    scheduler = AutomationScheduler(MQTTService(Settings()), factory)
    events = scheduler._run_due_rules()

    assert [event["type"] for event in events] == [
        "device_state",
        "automation_executed",
    ]
    with factory() as session:
        updated_device = session.get(Device, device.id)
        updated_rule = session.get(AutomationRule, rule.id)
        assert updated_device is not None
        assert simulated_state(updated_device) == {"power": True, "brightness": 100}
        assert updated_rule is not None
        assert updated_rule.last_run_at is not None
        assert updated_rule.next_run_at is not None
        assert updated_rule.last_error is None
