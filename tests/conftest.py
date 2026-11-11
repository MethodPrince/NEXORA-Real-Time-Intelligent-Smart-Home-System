import pytest

from app.core.config import get_settings


@pytest.fixture(autouse=True)
def configure_auth_secret(monkeypatch):
    monkeypatch.setenv(
        "NEXORA_JWT_SECRET_KEY",
        "test-only-signing-key-with-at-least-thirty-two-characters",
    )
    monkeypatch.setenv("DATABASE_URL", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
