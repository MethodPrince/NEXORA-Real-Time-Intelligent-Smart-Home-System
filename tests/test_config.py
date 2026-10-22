from app.core.config import Settings


def test_settings_read_environment_variables(monkeypatch) -> None:
    monkeypatch.setenv("NEXORA_APP_NAME", "NEXORA Test")
    monkeypatch.setenv("NEXORA_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://test_user:test_password@localhost:5432/test_db",
    )

    settings = Settings()

    assert settings.app_name == "NEXORA Test"
    assert settings.log_level == "DEBUG"
    assert settings.database_url == (
        "postgresql+psycopg://test_user:test_password@localhost:5432/test_db"
    )
