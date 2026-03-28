from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import TimestampedModel


class PatientBase(BaseModel):
    dni: str = Field(..., min_length=7, max_length=20)
    first_name: str = Field(..., max_length=80)
    last_name: str = Field(..., max_length=80)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=40)
    observations: str | None = None


class PatientCreate(PatientBase):
    pass


class PatientUpdate(BaseModel):
    dni: str | None = Field(default=None, min_length=7, max_length=20)
    first_name: str | None = Field(default=None, max_length=80)
    last_name: str | None = Field(default=None, max_length=80)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=40)
    observations: str | None = None
    is_active: bool | None = None


class PatientUpsert(PatientBase):
    first_name: str = Field(..., max_length=80)
    last_name: str = Field(..., max_length=80)


class PatientRead(TimestampedModel):
    dni: str
    first_name: str
    last_name: str
    email: EmailStr | None
    phone: str | None
    observations: str | None
    is_active: bool
