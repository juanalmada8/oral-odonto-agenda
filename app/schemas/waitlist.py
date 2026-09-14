from datetime import date

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.enums import WaitlistPeriod
from app.utils.validation import normalize_mobile_phone


class WaitlistJoin(BaseModel):
    professional_id: int | None = None
    date_from: date
    date_to: date
    period: WaitlistPeriod = WaitlistPeriod.ANY
    contact_email: EmailStr | None = None
    contact_phone: str | None = Field(default=None, max_length=40)
    notes: str | None = Field(default=None, max_length=500)

    @field_validator("contact_email")
    @classmethod
    def lowercase_email(cls, value: str | None) -> str | None:
        return value.lower() if value else value

    @field_validator("contact_phone")
    @classmethod
    def validate_phone(cls, value: str | None) -> str | None:
        return normalize_mobile_phone(value) if value else None
