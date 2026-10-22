from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_check_reports_backend_running(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.routes.health.check_database_connection",
        lambda: "not_configured",
    )
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "NEXORA",
        "database": "not_configured",
    }


def test_health_check_reports_database_status(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.routes.health.check_database_connection",
        lambda: "connected",
    )

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["database"] == "connected"
