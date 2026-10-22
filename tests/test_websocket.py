from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_websocket_echoes_messages() -> None:
    with client.websocket_connect("/ws") as websocket:
        websocket.send_text("hello")
        assert websocket.receive_text() == "NEXORA received: hello"

        websocket.send_text("second message")
        assert websocket.receive_text() == "NEXORA received: second message"


def test_test_event_broadcasts_to_all_clients_and_survives_disconnect() -> None:
    with client.websocket_connect("/ws") as client_a:
        with client.websocket_connect("/ws") as client_b:
            response = client.post("/events/test")

            assert response.status_code == 200
            event = response.json()
            assert event["type"] == "system_event"
            assert event["source"] == "nexora_backend"
            assert event["message"] == "NEXORA real-time system is working"
            assert event["timestamp"]
            assert client_a.receive_json() == event
            assert client_b.receive_json() == event

            client_a.close()

            next_response = client.post("/events/test")

            assert next_response.status_code == 200
            next_event = next_response.json()
            assert client_b.receive_json() == next_event
