from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from fastapi import WebSocketDisconnect
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.dependencies import get_db_session
from app.main import app
from app.websocket.connection_manager import ConnectionManager
from tests.auth_helpers import make_current_user_admin
from tests.auth_helpers import register_user


@pytest.fixture
def client(tmp_path) -> Generator[TestClient, None, None]:
    engine = create_engine(f"sqlite:///{(tmp_path / 'websocket.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_session():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    try:
        with TestClient(app) as test_client:
            register_user(test_client)
            make_current_user_admin(test_client, factory)
            yield test_client
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        engine.dispose()


def socket_protocols(token: str) -> list[str]:
    return ["nexora", f"bearer.{token}"]


def test_websocket_requires_a_valid_bearer_token(client: TestClient) -> None:
    home_id = client.headers["X-Home-ID"]
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/ws?home_id={home_id}"):
            pass

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            f"/ws?home_id={home_id}",
            subprotocols=["nexora", "bearer.invalid-token"],
            headers={"origin": "http://localhost:5173"},
        ):
            pass

    token = client.headers["Authorization"].removeprefix("Bearer ")
    with client.websocket_connect(
        f"/ws?home_id={home_id}",
        subprotocols=socket_protocols(token),
        headers={"origin": "http://localhost:5173"},
    ) as websocket:
        assert websocket.accepted_subprotocol == "nexora"
        websocket.send_text("hello")
        assert websocket.receive_text() == "NEXORA received: hello"


def test_authenticated_test_event_is_broadcast_to_own_connections(
    client: TestClient,
) -> None:
    token = client.headers["Authorization"].removeprefix("Bearer ")
    home_id = client.headers["X-Home-ID"]
    with client.websocket_connect(
        f"/ws?home_id={home_id}",
        subprotocols=socket_protocols(token),
        headers={"origin": "http://localhost:5173"},
    ) as socket_a:
        with client.websocket_connect(
            f"/ws?home_id={home_id}",
            subprotocols=socket_protocols(token),
            headers={"origin": "http://localhost:5173"},
        ) as socket_b:
            response = client.post("/events/test")
            assert response.status_code == 200
            event = response.json()
            assert event["type"] == "system_event"
            assert socket_a.receive_json() == event
            assert socket_b.receive_json() == event


def test_user_websocket_broadcasts_are_isolated() -> None:
    class FakeSocket:
        def __init__(self) -> None:
            self.messages: list[dict[str, object]] = []

        async def send_json(self, message: dict[str, object]) -> None:
            self.messages.append(message)

    import asyncio
    from uuid import uuid4

    manager = ConnectionManager()
    home_id = uuid4()
    other_home_id = uuid4()
    owner_id = uuid4()
    owner_socket = FakeSocket()
    other_socket = FakeSocket()

    async def verify() -> None:
        async with manager._lock:
            manager.active_connections = {
                (home_id, owner_id): {owner_socket},
                (other_home_id, owner_id): {other_socket},
            }
        await manager.broadcast_to_home(home_id, {"type": "device_state"})

    asyncio.run(verify())
    assert owner_socket.messages == [{"type": "device_state"}]
    assert other_socket.messages == []
