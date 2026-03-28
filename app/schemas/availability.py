from datetime import date, datetime, time

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import TimestampedModel


class AvailabilitySlot(BaseModel):
    starts_at: datetime
    ends_at: datetime
    available: bool = True


class DailyAvailabilityRead(BaseModel):
    professional_id: int
    date: date
    slots: list[AvailabilitySlot]


class WeeklyAvailabilityDay(BaseModel):
    date: date
    slots: list[AvailabilitySlot]


class WeeklyAvailabilityRead(BaseModel):
    professional_id: int
    week_start: date
    days: list[WeeklyAvailabilityDay]


class WorkingHoursSummary(BaseModel):
    day_of_week: int
    start_time: time
    end_time: time
    slot_duration_minutes: int | None


class AvailabilityWindowBase(BaseModel):
    professional_id: int
    availability_date: date
    start_time: time
    end_time: time
    slot_duration_minutes: int | None = Field(default=None, ge=10, le=240)
    notes: str | None = None

    @field_validator("end_time")
    @classmethod
    def validate_time_range(cls, value: time, info) -> time:
        start_time = info.data.get("start_time")
        if start_time and value <= start_time:
            raise ValueError("end_time must be later than start_time")
        return value


class AvailabilityWindowCreate(AvailabilityWindowBase):
    pass


class AvailabilityWindowUpdate(BaseModel):
    availability_date: date | None = None
    start_time: time | None = None
    end_time: time | None = None
    slot_duration_minutes: int | None = Field(default=None, ge=10, le=240)
    notes: str | None = None


class AvailabilityWindowRead(TimestampedModel):
    professional_id: int
    availability_date: date
    start_time: time
    end_time: time
    slot_duration_minutes: int | None
    notes: str | None
