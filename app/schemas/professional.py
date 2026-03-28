from datetime import date, time

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas.common import TimestampedModel


class ProfessionalBase(BaseModel):
    first_name: str = Field(..., max_length=80)
    last_name: str = Field(..., max_length=80)
    specialty: str | None = Field(default=None, max_length=120)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=40)
    default_appointment_duration: int = Field(default=30, ge=10, le=240)


class ProfessionalCreate(ProfessionalBase):
    pass


class ProfessionalUpdate(BaseModel):
    first_name: str | None = Field(default=None, max_length=80)
    last_name: str | None = Field(default=None, max_length=80)
    specialty: str | None = Field(default=None, max_length=120)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=40)
    default_appointment_duration: int | None = Field(default=None, ge=10, le=240)
    is_active: bool | None = None


class ProfessionalRead(TimestampedModel):
    first_name: str
    last_name: str
    specialty: str | None
    email: EmailStr | None
    phone: str | None
    default_appointment_duration: int
    is_active: bool


class WorkingHoursBase(BaseModel):
    professional_id: int
    day_of_week: int = Field(..., ge=0, le=6)
    start_time: time
    end_time: time
    slot_duration_minutes: int | None = Field(default=None, ge=10, le=240)

    @field_validator("end_time")
    @classmethod
    def validate_range(cls, value: time, info) -> time:
        start_time = info.data.get("start_time")
        if start_time and value <= start_time:
            raise ValueError("end_time must be later than start_time")
        return value


class WorkingHoursCreate(WorkingHoursBase):
    pass


class WorkingHoursUpdate(BaseModel):
    day_of_week: int | None = Field(default=None, ge=0, le=6)
    start_time: time | None = None
    end_time: time | None = None
    slot_duration_minutes: int | None = Field(default=None, ge=10, le=240)


class WorkingHoursRead(TimestampedModel):
    professional_id: int
    day_of_week: int
    start_time: time
    end_time: time
    slot_duration_minutes: int | None


class HolidayBlockBase(BaseModel):
    name: str = Field(..., max_length=120)
    start_date: date
    end_date: date
    reason: str | None = None
    professional_id: int | None = None

    @field_validator("end_date")
    @classmethod
    def validate_end_date(cls, value, info):
        start_date = info.data.get("start_date")
        if start_date and value < start_date:
            raise ValueError("end_date must be on or after start_date")
        return value


class HolidayBlockCreate(HolidayBlockBase):
    pass


class HolidayBlockRead(TimestampedModel):
    name: str
    start_date: date
    end_date: date
    reason: str | None
    professional_id: int | None
