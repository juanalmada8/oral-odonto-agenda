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


class RecurringAvailabilityCreate(BaseModel):
    """Repeat the same time block on chosen weekdays between two dates."""

    professional_id: int
    date_from: date
    date_to: date
    weekdays: list[int] = Field(..., min_length=1)
    start_time: time
    end_time: time
    slot_duration_minutes: int | None = Field(default=None, ge=10, le=240)
    notes: str | None = None

    @field_validator("weekdays")
    @classmethod
    def validate_weekdays(cls, value: list[int]) -> list[int]:
        if any(day < 0 or day > 6 for day in value):
            raise ValueError("Los días de la semana van de 0 (lunes) a 6 (domingo).")
        return sorted(set(value))

    @field_validator("date_to")
    @classmethod
    def validate_range(cls, value: date, info) -> date:
        date_from = info.data.get("date_from")
        if date_from and value < date_from:
            raise ValueError("La fecha final tiene que ser igual o posterior a la inicial.")
        if date_from and (value - date_from).days > 185:
            raise ValueError("Cargá como máximo 6 meses por vez.")
        return value

    @field_validator("end_time")
    @classmethod
    def validate_time_range(cls, value: time, info) -> time:
        start_time = info.data.get("start_time")
        if start_time and value <= start_time:
            raise ValueError("La hora de fin debe ser posterior a la de inicio.")
        return value


class AvailabilityBulkResult(BaseModel):
    created: int = 0
    removed: int = 0
    # Dates left untouched: clashing/past ones when creating, ones with appointments when clearing.
    skipped_dates: list[date] = []
