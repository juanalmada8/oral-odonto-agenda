import os
from decimal import Decimal
from functools import lru_cache

from pydantic import Field, computed_field, field_validator, model_validator
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
    # Per instance. Cloud SQL db-f1-micro allows ~25 connections: keep (pool+overflow) x instances below it.
    db_pool_size: int = Field(default=5, ge=1, le=50)
    db_max_overflow: int = Field(default=5, ge=0, le=50)

    # "json" emits Cloud Logging structured lines; "text" is friendlier locally.
    log_format: str = "text"
    # Used to link log lines to Cloud Trace (set automatically on Cloud Run via GOOGLE_CLOUD_PROJECT).
    google_cloud_project: str | None = None

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = True
    email_from: str | None = None


    reminder_hours_ahead: int = Field(default=24, ge=1, le=168)
    # Hour of the day (clinic time) from which each professional gets tomorrow's agenda by email.
    professional_digest_hour: int = Field(default=18, ge=0, le=23)
    notification_max_attempts: int = Field(default=4, ge=1, le=10)

    # WhatsApp Cloud API (Meta). Reminders use an approved template with two quick-reply buttons.
    whatsapp_access_token: str | None = None
    whatsapp_phone_number_id: str | None = None
    whatsapp_app_secret: str | None = None
    whatsapp_verify_token: str | None = None
    whatsapp_api_version: str = "v21.0"
    whatsapp_reminder_template: str = "recordatorio_turno"
    whatsapp_template_language: str = "es_AR"

    # Clinic identity shown to patients (emails, WhatsApp, booking pages).
    clinic_name: str = "ORAL odontología familiar"
    clinic_address: str | None = None
    clinic_city: str = "General Belgrano, Buenos Aires"
    clinic_phone: str | None = None
    # Free text shown on the booking page, e.g. "Lunes a viernes de 9 a 19".
    clinic_hours: str | None = None
    clinic_whatsapp: str | None = None  # E.164, opens wa.me
    clinic_instagram: str | None = None  # handle without @
    clinic_maps_url: str | None = None
    # Absolute URL where the site is reachable; used for payment callbacks and links in messages.
    public_base_url: str = "http://localhost:8000"

    # Public booking rules.
    booking_min_lead_minutes: int = Field(default=120, ge=0)
    booking_max_days_ahead: int = Field(default=60, ge=1, le=365)
    booking_max_active_per_patient: int = Field(default=2, ge=1)
    # Minutes a slot stays held while the patient pays the deposit.
    booking_hold_minutes: int = Field(default=20, ge=5, le=120)
    # Patients may cancel on their own (link / WhatsApp) up to this many hours before the visit.
    cancellation_notice_hours: int = Field(default=24, ge=0)

    # Deposit ("seña"). Professionals can override the amount; 0 disables deposits.
    deposit_default_amount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=12, decimal_places=2)
    currency: str = "ARS"
    deposit_policy: str = (
        "La seña se descuenta del valor de la consulta. Si cancelás con al menos 24 horas de "
        "anticipación podés reprogramar sin costo; con menos aviso, la seña no es reembolsable."
    )

    # Mercado Pago Checkout Pro. Without an access token (outside production) a local simulator is used.
    mercadopago_access_token: str | None = None
    mercadopago_webhook_secret: str | None = None
    mercadopago_statement_descriptor: str = "ORAL ODONTOLOGIA"

    # Abuse protection. Behind Cloud Run / a load balancer the client IP arrives in X-Forwarded-For.
    trust_proxy_headers: bool = False
    # Proxies that append to X-Forwarded-For: 1 on plain Cloud Run, 2 behind an external load balancer.
    trusted_proxy_count: int = Field(default=1, ge=1, le=5)
    booking_rate_limit_per_hour: int = Field(default=10, ge=1)
    login_rate_limit_per_15_minutes: int = Field(default=10, ge=1)

    model_config = SettingsConfigDict(
        # APP_ENV_FILE="" disables the dotenv file (tests must never pick up real SMTP/API credentials).
        env_file=os.environ.get("APP_ENV_FILE", ".env") or None,
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    @computed_field
    @property
    def docs_enabled(self) -> bool:
        return self.app_env != "production" or self.debug

    @computed_field
    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    @field_validator("database_url", "test_database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, value):
        # Managed PostgreSQL providers hand out postgres:// or postgresql:// URLs, which SQLAlchemy
        # maps to psycopg2. This project ships psycopg 3, so pin the driver explicitly.
        if isinstance(value, str):
            for prefix in ("postgres://", "postgresql://"):
                if value.startswith(prefix):
                    return "postgresql+psycopg://" + value.removeprefix(prefix)
        return value

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
        if not self.public_base_url.startswith("https://"):
            raise ValueError("PUBLIC_BASE_URL must be an https:// URL in production")
        if self.whatsapp_access_token and not self.whatsapp_app_secret:
            raise ValueError("WHATSAPP_APP_SECRET is required to verify WhatsApp webhooks in production")
        if self.deposit_default_amount > 0 and not self.mercadopago_access_token:
            raise ValueError("MERCADOPAGO_ACCESS_TOKEN is required when DEPOSIT_DEFAULT_AMOUNT > 0 in production")
        return self

    @field_validator("public_base_url")
    @classmethod
    def strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()
