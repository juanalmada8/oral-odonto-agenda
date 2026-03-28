from functools import lru_cache

from pydantic import computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "ORAL"
    app_env: str = "development"
    debug: bool = True
    api_prefix: str = "/api/v1"
    app_timezone: str = "America/Argentina/Buenos_Aires"
    secret_key: str = "change-me"
    access_token_expire_minutes: int = 60 * 8

    database_url: str = "postgresql+psycopg://postgres:postgres@db:5432/odonto_agenda"
    test_database_url: str = "sqlite+pysqlite:///:memory:"

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = True
    email_from: str | None = None

    openai_api_key: str | None = None
    openai_model: str = "gpt-5-mini"

    reminder_hours_ahead: int = 24

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    @computed_field
    @property
    def docs_enabled(self) -> bool:
        return self.app_env != "production" or self.debug

    @field_validator("debug", mode="before")
    @classmethod
    def parse_debug(cls, value):
        if isinstance(value, bool):
            return value
        if value is None:
            return True
        normalized = str(value).strip().lower()
        if normalized in {"1", "true", "yes", "on", "debug"}:
            return True
        if normalized in {"0", "false", "no", "off", "release", "prod", "production"}:
            return False
        raise ValueError("Invalid debug value")


@lru_cache
def get_settings() -> Settings:
    return Settings()
