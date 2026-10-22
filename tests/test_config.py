from app.core.config import Settings


def test_settings_read_environment_variables(monkeypatch) -> None:
    monkeypatch.setenv("NEXORA_APP_NAME", "NEXORA Test")
    monkeypatch.setenv("NEXORA_LOG_LEVEL", "DEBUG")

    settings = Settings()

    assert settings.app_name == "NEXORA Test"
    assert settings.log_level == "DEBUG"
