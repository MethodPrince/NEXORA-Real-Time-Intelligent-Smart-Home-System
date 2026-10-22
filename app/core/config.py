from functools import lru_cache

from pydantic import AliasChoices
from pydantic import Field
from pydantic import field_validator
from pydantic import model_validator
from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "NEXORA"
    environment: str = "development"
    log_level: str = "INFO"
    database_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("DATABASE_URL", "NEXORA_DATABASE_URL"),
        repr=False,
    )
    mqtt_enabled: bool = False
    mqtt_host: str = "localhost"
    mqtt_port: int = Field(default=1883, ge=1, le=65535)
    mqtt_username: str | None = Field(default=None, repr=False)
    mqtt_password: str | None = Field(default=None, repr=False)
    mqtt_tls_enabled: bool = False
    mqtt_client_id: str = "nexora-backend"
    mqtt_keepalive: int = Field(default=60, gt=0)

    @field_validator("mqtt_username", "mqtt_password", mode="before")
    @classmethod
    def normalize_empty_mqtt_credentials(cls, value: object) -> object:
        return None if value == "" else value

    @model_validator(mode="after")
    def validate_mqtt_credentials(self) -> "Settings":
        if self.mqtt_password and not self.mqtt_username:
            raise ValueError("NEXORA_MQTT_USERNAME is required with a password")
        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="NEXORA_",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
