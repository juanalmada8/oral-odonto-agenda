from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas.common import TimestampedModel
from app.utils.validation import normalize_dni, normalize_mobile_phone, normalize_person_name


class PatientBase(BaseModel):
    dni: str = Field(..., min_length=6, max_length=20)
    first_name: str = Field(..., max_length=80)
    last_name: str = Field(..., max_length=80)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=40)
    observations: str | None = Field(default=None, max_length=1000)

    @field_validator("dni")
    @classmethod
    def validate_dni(cls, value: str) -> str:
        return normalize_dni(value, strict=False)

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
    def lowercase_email(cls, value: str | None) -> str | None:
        return value.lower() if value else value

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str | None) -> str | None:
        return normalize_mobile_phone(value) if value else None


class PatientCreate(PatientBase):
    pass


class PatientUpdate(BaseModel):
    dni: str | None = Field(default=None, min_length=6, max_length=20)
    first_name: str | None = Field(default=None, max_length=80)
    last_name: str | None = Field(default=None, max_length=80)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=40)
    observations: str | None = Field(default=None, max_length=1000)
    is_active: bool | None = None

    @field_validator("dni")
    @classmethod
    def validate_dni(cls, value: str | None) -> str | None:
        return normalize_dni(value, strict=False) if value is not None else None

    @field_validator("first_name")
    @classmethod
    def validate_first_name(cls, value: str | None) -> str | None:
        return normalize_person_name(value, label="El nombre") if value is not None else None

    @field_validator("last_name")
    @classmethod
    def validate_last_name(cls, value: str | None) -> str | None:
        return normalize_person_name(value, label="El apellido") if value is not None else None

    @field_validator("email")
    @classmethod
    def lowercase_email(cls, value: str | None) -> str | None:
        return value.lower() if value else value

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str | None) -> str | None:
        return normalize_mobile_phone(value) if value else None


class PatientUpsert(PatientBase):
    pass


class PatientRead(TimestampedModel):
    dni: str
    first_name: str
    last_name: str
    email: EmailStr | None
    phone: str | None
    observations: str | None
    is_active: bool
