from functools import lru_cache

from pydantic import AliasChoices
from pydantic import Field
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
