import asyncio
from collections.abc import Generator
from types import SimpleNamespace
from uuid import UUID
from uuid import uuid4

import paho.mqtt.client as mqtt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker

from app.api.routes.device_commands import get_mqtt_service
from app.core.config import Settings
from app.db.base import Base
from app.db.dependencies import get_db_session
from app.db.models import Device
from app.services.mqtt import INBOUND_TOPICS
from app.services.mqtt import MQTTService
from app.services.mqtt import MQTTServiceUnavailableError
from app.main import app


class FakeMQTTClient:
    def __init__(self, **_kwargs) -> None:
        self.subscriptions: list[tuple[str, int]] = []
        self.publications: list[tuple[str, str, int]] = []
        self.connected_to: tuple[str, int, int] | None = None
        self.loop_started = False
        self.loop_stopped = False

    def username_pw_set(self, _username: str, _password: str | None) -> None:
        pass

    def tls_set(self) -> None:
        pass

    def connect_async(self, host: str, port: int, keepalive: int) -> int:
        self.connected_to = (host, port, keepalive)
        return mqtt.MQTT_ERR_SUCCESS

    def loop_start(self) -> None:
        self.loop_started = True

    def loop_stop(self) -> None:
        self.loop_stopped = True

    def disconnect(self) -> None:
        pass

    def subscribe(self, topic: str, qos: int) -> tuple[int, int]:
        self.subscriptions.append((topic, qos))
        return mqtt.MQTT_ERR_SUCCESS, len(self.subscriptions)

    def publish(self, topic: str, payload: str, qos: int):
        self.publications.append((topic, payload, qos))
        return SimpleNamespace(rc=mqtt.MQTT_ERR_SUCCESS)


@pytest.fixture
def isolated_db(tmp_path, monkeypatch) -> Generator[tuple[object, str], None, None]:
    database_path = tmp_path / "mqtt.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    monkeypatch.setattr("app.services.mqtt.get_engine", lambda: engine)
    try:
        yield engine, database_url
    finally:
        engine.dispose()


def make_service(monkeypatch) -> MQTTService:
    fake_client = FakeMQTTClient()
    monkeypatch.setattr("app.services.mqtt.mqtt.Client", lambda **kwargs: fake_client)
    service = MQTTService(
        Settings(
            mqtt_enabled=True,
            mqtt_host="broker.test",
            mqtt_port=1884,
            mqtt_keepalive=30,
            mqtt_username="test-user",
            mqtt_password="test-password",
            mqtt_tls_enabled=True,
        )
    )
    service._test_client = fake_client
    return service


def connect_fake_client(service: MQTTService, fake_client: FakeMQTTClient) -> None:
    service._on_connect(
        fake_client,
        None,
        None,
        SimpleNamespace(is_failure=False),
        None,
    )


def test_mqtt_lifecycle_subscribes_after_each_connection_and_reconnect(
    monkeypatch,
) -> None:
    service = make_service(monkeypatch)
    client = service._test_client
    asyncio.run(_start_service(service))

    assert client.connected_to == ("broker.test", 1884, 30)
    assert client.loop_started
    assert not service.connected

    connect_fake_client(service, client)
    assert service.connected
    assert client.subscriptions == [(topic, 1) for topic in INBOUND_TOPICS]

    service._on_disconnect(
        client,
        None,
        None,
        SimpleNamespace(is_failure=True),
        None,
    )
    assert not service.connected
    connect_fake_client(service, client)
    assert service.connected
    assert len(client.subscriptions) == 2 * len(INBOUND_TOPICS)

    asyncio.run(service.stop())
    assert client.loop_stopped
    assert not service.connected


async def _start_service(service: MQTTService) -> None:
    service.start()


def test_publish_device_command_uses_command_topic_and_qos_one(
    monkeypatch,
) -> None:
    service = make_service(monkeypatch)
    client = service._test_client
    connect_fake_client(service, client)
    device_id = uuid4()

    topic = service.publish_device_command(
        device_id,
        "set_temperature",
        {"value": 21.5},
    )

    assert topic == f"nexora/devices/{device_id}/command"
    assert client.publications == [
        (
            topic,
            '{"command":"set_temperature","parameters":{"value":21.5}}',
            1,
        )
    ]


def test_publish_device_command_fails_when_broker_is_disconnected(
    monkeypatch,
) -> None:
    service = make_service(monkeypatch)

    with pytest.raises(MQTTServiceUnavailableError):
        service.publish_device_command(uuid4(), "turn_on", {})


def test_inbound_messages_update_existing_models_and_broadcast(
    isolated_db,
    monkeypatch,
) -> None:
    engine, _database_url = isolated_db
    device_id = uuid4()
    with Session(engine) as session:
        session.add(Device(id=device_id, name="ESP32", device_type="sensor"))
        session.commit()

    broadcasts: list[dict[str, object]] = []

    async def capture_broadcast(event: dict[str, object]) -> None:
        broadcasts.append(event)

    monkeypatch.setattr(
        "app.services.mqtt.connection_manager.broadcast",
        capture_broadcast,
    )
    service = MQTTService(Settings())
    messages = [
        (
            f"nexora/devices/{device_id}/state",
            b'{"status":"active"}',
        ),
        (
            f"nexora/devices/{device_id}/sensor",
            b'{"name":"Temperature","sensor_type":"temperature","reading":21.5,"unit":"C"}',
        ),
        (
            f"nexora/devices/{device_id}/availability",
            b"online",
        ),
    ]

    async def deliver_from_mqtt_thread() -> None:
        service._loop = asyncio.get_running_loop()
        for topic, payload in messages:
            await asyncio.to_thread(
                service._on_message,
                None,
                None,
                SimpleNamespace(topic=topic, payload=payload),
            )

        async def wait_for_broadcasts() -> None:
            while len(broadcasts) < len(messages):
                await asyncio.sleep(0.01)

        await asyncio.wait_for(wait_for_broadcasts(), timeout=2)

    asyncio.run(deliver_from_mqtt_thread())

    with Session(engine) as session:
        device = session.get(Device, device_id)
        assert device is not None
        assert device.status == "active"
        assert device.online is True
        assert len(device.sensors) == 1
        assert device.sensors[0].reading == pytest.approx(21.5)
        assert device.sensors[0].unit == "C"

    assert [event["type"] for event in broadcasts] == [
        "device_state",
        "device_sensor",
        "device_availability",
    ]
    assert broadcasts[0]["status"] == "active"
    assert broadcasts[1]["reading"] == pytest.approx(21.5)
    assert broadcasts[2]["online"] is True


def test_invalid_or_unknown_inbound_messages_are_not_broadcast(
    isolated_db,
    monkeypatch,
) -> None:
    broadcasts: list[dict[str, object]] = []

    async def capture_broadcast(event: dict[str, object]) -> None:
        broadcasts.append(event)

    monkeypatch.setattr(
        "app.services.mqtt.connection_manager.broadcast",
        capture_broadcast,
    )
    service = MQTTService(Settings())
    async def process_messages() -> None:
        await service._process_message("nexora/devices/not-a-uuid/state", b'{"status":"ok"}')
        await service._process_message(
            f"nexora/devices/{uuid4()}/availability",
            b"unknown",
        )
        await service._process_message(
            f"nexora/devices/{uuid4()}/sensor",
            b'{"reading":NaN}',
        )

    asyncio.run(process_messages())
    assert broadcasts == []


@pytest.fixture
def command_api(
    tmp_path,
) -> Generator[
    tuple[TestClient, list[tuple[UUID, str, dict[str, object]]], UUID],
    None,
    None,
]:
    database_path = tmp_path / "command-api.db"
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    published: list[tuple[UUID, str, dict[str, object]]] = []
    device_id = uuid4()

    def override_session():
        with session_factory() as session:
            yield session

    class AvailableMQTTService:
        def publish_device_command(
            self,
            device_id: UUID,
            command: str,
            parameters: dict[str, object],
        ) -> str:
            published.append((device_id, command, parameters))
            return f"nexora/devices/{device_id}/command"

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_mqtt_service] = lambda: AvailableMQTTService()
    try:
        with TestClient(app) as client:
            with Session(engine) as session:
                session.add(
                    Device(
                        id=device_id,
                        name="ESP32",
                        device_type="light",
                    )
                )
                session.commit()
            yield client, published, device_id
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        app.dependency_overrides.pop(get_mqtt_service, None)
        engine.dispose()


def test_device_command_api_validates_device_and_publishes(command_api) -> None:
    client, published, device_id = command_api

    response = client.post(
        f"/devices/{device_id}/command",
        json={"command": "set_power", "parameters": {"enabled": True}},
    )
    assert response.status_code == 202
    assert response.json() == {
        "device_id": str(device_id),
        "topic": f"nexora/devices/{device_id}/command",
        "status": "queued",
    }
    assert published == [(device_id, "set_power", {"enabled": True})]

    missing = client.post(
        f"/devices/{uuid4()}/command",
        json={"command": "turn_on"},
    )
    assert missing.status_code == 404


def test_device_command_api_rejects_invalid_payload(command_api) -> None:
    client, _published, device_id = command_api
    response = client.post(
        f"/devices/{device_id}/command",
        json={"command": "  ", "unexpected": True},
    )
    assert response.status_code == 422


def test_device_command_api_reports_unavailable_broker(
    command_api,
) -> None:
    client, _published, device_id = command_api

    class OfflineMQTTService:
        def publish_device_command(
            self,
            _device_id: UUID,
            _command: str,
            _parameters: dict[str, object],
        ) -> str:
            raise MQTTServiceUnavailableError("details should not be exposed")

    app.dependency_overrides[get_mqtt_service] = lambda: OfflineMQTTService()
    try:
        response = client.post(
            f"/devices/{device_id}/command",
            json={"command": "turn_on"},
        )
    finally:
        app.dependency_overrides.pop(get_mqtt_service, None)

    assert response.status_code == 503
    assert response.json() == {"detail": "MQTT broker is unavailable"}
