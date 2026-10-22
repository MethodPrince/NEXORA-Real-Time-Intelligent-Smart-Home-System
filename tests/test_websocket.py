from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_websocket_echoes_messages() -> None:
    with client.websocket_connect("/ws") as websocket:
        websocket.send_text("hello")
        assert websocket.receive_text() == "NEXORA received: hello"

        websocket.send_text("second message")
        assert websocket.receive_text() == "NEXORA received: second message"
