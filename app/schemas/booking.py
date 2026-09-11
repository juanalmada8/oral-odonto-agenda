from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.utils.validation import normalize_dni, normalize_mobile_phone, normalize_person_name


class PublicBookingRequest(BaseModel):
    """Data a patient submits from /reservar. Stricter than staff forms on purpose."""

    professional_id: int = Field(..., gt=0)
    starts_at: datetime
    dni: str
    first_name: str
    last_name: str
    email: EmailStr
    phone: str
    reason: str | None = Field(default=None, max_length=255)
    observations: str | None = Field(default=None, max_length=1000)
    accept_terms: bool

    @field_validator("dni")
    @classmethod
    def validate_dni(cls, value: str) -> str:
        return normalize_dni(value, strict=True)

    @field_validator("first_name")
    @classmethod
    def validate_first_name(cls, value: str) -> str:
        return normalize_person_name(value, label="El nombre")

    @field_validator("last_name")
    @classmethod
    def validate_last_name(cls, value: str) -> str:
        return normalize_person_name(value, label="El apellido")

    @field_validator("email")
    @classmethod
    def lowercase_email(cls, value: str) -> str:
        return value.lower()

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        return normalize_mobile_phone(value)

    @field_validator("reason", "observations", mode="before")
    @classmethod
    def blank_to_none(cls, value):
        if isinstance(value, str):
            value = value.strip()
        return value or None

    @field_validator("accept_terms")
    @classmethod
    def require_terms(cls, value: bool) -> bool:
        if not value:
            raise ValueError("Tenés que aceptar la política de seña y cancelación para reservar.")
        return value
