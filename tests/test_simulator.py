from collections.abc import Generator
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker

from app.api.routes.device_commands import get_mqtt_service
from app.db.base import Base
from app.db.dependencies import get_db_session
from app.main import app


@pytest.fixture
def client(tmp_path) -> Generator[TestClient, None, None]:
    database_path = tmp_path / "simulator.db"
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )

    def override_database_session() -> Generator[Session, None, None]:
        with session_factory() as session:
            yield session

    class UnexpectedMQTTService:
        def publish_device_command(
            self,
            _device_id: UUID,
            _command: str,
            _parameters: dict[str, object],
        ) -> str:
            raise AssertionError("simulated commands must not be published to MQTT")

    app.dependency_overrides[get_db_session] = override_database_session
    app.dependency_overrides[get_mqtt_service] = lambda: UnexpectedMQTTService()
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        app.dependency_overrides.pop(get_mqtt_service, None)
        engine.dispose()


@pytest.mark.parametrize(
    ("device_type", "initial_state", "initial_status"),
    [
        ("smart_light", {"power": False, "brightness": 100}, "Off"),
        ("smart_fan", {"power": False, "speed": 0}, "Off"),
        ("smart_curtain", {"position": 0}, "Closed"),
    ],
)
def test_simulated_device_creation_initializes_online_state(
    client: TestClient,
    device_type: str,
    initial_state: dict[str, object],
    initial_status: str,
) -> None:
    response = client.post(
        "/devices",
        json={
            "name": "Simulated device",
            "device_type": device_type,
            "simulated": True,
        },
    )

    assert response.status_code == 201
    device = response.json()
    assert device["simulated"] is True
    assert device["online"] is True
    assert device["state"] == initial_state
    assert device["status"] == initial_status

    persisted = client.get(f"/devices/{device['id']}")
    assert persisted.status_code == 200
    assert persisted.json()["state"] == initial_state


def test_simulated_device_can_be_created_offline(client: TestClient) -> None:
    response = client.post(
        "/devices",
        json={
            "name": "Offline light",
            "device_type": "light",
            "simulated": True,
            "online": False,
        },
    )

    assert response.status_code == 201
    assert response.json()["online"] is False


def test_simulated_device_rejects_unsupported_type(client: TestClient) -> None:
    response = client.post(
        "/devices",
        json={
            "name": "Unsupported simulator",
            "device_type": "temperature_sensor",
            "simulated": True,
        },
    )

    assert response.status_code == 422


def test_light_commands_persist_and_broadcast_state(client: TestClient) -> None:
    created = client.post(
        "/devices",
        json={"name": "Desk lamp", "device_type": "light", "simulated": True},
    ).json()

    with client.websocket_connect("/ws") as websocket:
        powered = client.post(
            f"/devices/{created['id']}/command",
            json={"command": "set_power", "parameters": {"enabled": True}},
        )
        event = websocket.receive_json()

    assert powered.status_code == 202
    assert powered.json() == {
        "device_id": created["id"],
        "status": "applied",
        "online": True,
        "state": {"power": True, "brightness": 100},
    }
    assert event["type"] == "device_state"
    assert event["device_id"] == created["id"]
    assert event["status"] == "On"
    assert event["online"] is True
    assert event["state"] == {"power": True, "brightness": 100}

    brightness = client.post(
        f"/devices/{created['id']}/command",
        json={"command": "set_brightness", "parameters": {"brightness": 35}},
    )
    assert brightness.status_code == 202
    assert brightness.json()["state"] == {"power": True, "brightness": 35}
    assert client.get(f"/devices/{created['id']}").json()["state"] == {
        "power": True,
        "brightness": 35,
    }


def test_fan_commands_manage_power_and_speed(client: TestClient) -> None:
    created = client.post(
        "/devices",
        json={"name": "Ceiling fan", "device_type": "fan", "simulated": True},
    ).json()

    speed = client.post(
        f"/devices/{created['id']}/command",
        json={"command": "set_speed", "parameters": {"speed": 2}},
    )
    assert speed.status_code == 202
    assert speed.json()["state"] == {"power": True, "speed": 2}

    powered_off = client.post(
        f"/devices/{created['id']}/command",
        json={"command": "set_power", "parameters": {"enabled": False}},
    )
    assert powered_off.status_code == 202
    assert powered_off.json()["state"] == {"power": False, "speed": 0}
    assert client.get(f"/devices/{created['id']}").json()["status"] == "Off"


def test_curtain_commands_manage_open_and_position(client: TestClient) -> None:
    created = client.post(
        "/devices",
        json={"name": "Living room curtain", "device_type": "curtain", "simulated": True},
    ).json()

    opened = client.post(
        f"/devices/{created['id']}/command",
        json={"command": "open"},
    )
    assert opened.status_code == 202
    assert opened.json()["state"] == {"position": 100}
    assert client.get(f"/devices/{created['id']}").json()["status"] == "Open"

    positioned = client.post(
        f"/devices/{created['id']}/command",
        json={"command": "set_position", "parameters": {"position": 40}},
    )
    assert positioned.status_code == 202
    assert positioned.json()["state"] == {"position": 40}
    assert client.get(f"/devices/{created['id']}").json()["status"] == "Partially open"

    closed = client.post(
        f"/devices/{created['id']}/command",
        json={"command": "close"},
    )
    assert closed.status_code == 202
    assert closed.json()["state"] == {"position": 0}


@pytest.mark.parametrize(
    ("command", "parameters"),
    [
        ("blink", {}),
        ("set_brightness", {"brightness": 101}),
        ("set_brightness", {"brightness": True}),
        ("set_power", {"enabled": "yes"}),
        ("set_power", {"enabled": True, "extra": 1}),
    ],
)
def test_invalid_simulated_light_commands_do_not_change_state(
    client: TestClient,
    command: str,
    parameters: dict[str, object],
) -> None:
    created = client.post(
        "/devices",
        json={"name": "Desk lamp", "device_type": "light", "simulated": True},
    ).json()
    response = client.post(
        f"/devices/{created['id']}/command",
        json={"command": command, "parameters": parameters},
    )

    assert response.status_code == 422
    assert client.get(f"/devices/{created['id']}").json()["state"] == {
        "power": False,
        "brightness": 100,
    }


def test_offline_simulated_device_rejects_commands(client: TestClient) -> None:
    created = client.post(
        "/devices",
        json={"name": "Offline fan", "device_type": "fan", "simulated": True},
    ).json()
    client.patch(f"/devices/{created['id']}", json={"online": False})

    response = client.post(
        f"/devices/{created['id']}/command",
        json={"command": "set_speed", "parameters": {"speed": 3}},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Simulated device is offline"}
    assert client.get(f"/devices/{created['id']}").json()["state"] == {
        "power": False,
        "speed": 0,
    }
