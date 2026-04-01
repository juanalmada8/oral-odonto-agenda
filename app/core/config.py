from functools import lru_cache

from pydantic import computed_field, field_validator, model_validator
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

    @model_validator(mode="after")
    def validate_production_safety(self):
        if self.app_env.lower() != "production":
            return self

        if self.secret_key == "change-me":
            raise ValueError("SECRET_KEY must be changed in production")
        if len(self.secret_key) < 32:
            raise ValueError("SECRET_KEY must have at least 32 characters in production")
        if self.database_url.startswith("sqlite"):
            raise ValueError("DATABASE_URL must use PostgreSQL in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
