from datetime import date, datetime

from pydantic import BaseModel, Field, model_validator

from app.core.enums import AppointmentStatus
from app.schemas.common import TimestampedModel
from app.schemas.patient import PatientRead, PatientUpsert
from app.schemas.professional import ProfessionalRead


class AppointmentCreate(BaseModel):
    professional_id: int
    patient_id: int | None = None
    patient: PatientUpsert | None = None
    starts_at: datetime
    duration_minutes: int | None = Field(default=None, ge=10, le=240)
    reason: str | None = Field(default=None, max_length=255)
    notes: str | None = None
    created_by: str = Field(default="reception_agent", max_length=80)

    @model_validator(mode="after")
    def validate_patient_source(self):
        if not self.patient_id and not self.patient:
            raise ValueError("patient_id or patient payload is required")
        return self


class AppointmentUpdate(BaseModel):
    starts_at: datetime | None = None
    duration_minutes: int | None = Field(default=None, ge=10, le=240)
    status: AppointmentStatus | None = None
    reason: str | None = Field(default=None, max_length=255)
    notes: str | None = None


class AppointmentReschedule(BaseModel):
    starts_at: datetime
    duration_minutes: int | None = Field(default=None, ge=10, le=240)


class AppointmentStatusUpdate(BaseModel):
    notes: str | None = None


class AppointmentRead(TimestampedModel):
    patient_id: int
    professional_id: int
    starts_at: datetime
    ends_at: datetime
    duration_minutes: int
    status: AppointmentStatus
    reason: str | None
    notes: str | None
    confirmed_at: datetime | None
    cancelled_at: datetime | None
    created_by: str
    patient: PatientRead
    professional: ProfessionalRead


class AppointmentListItem(TimestampedModel):
    patient_id: int
    professional_id: int
    starts_at: datetime
    ends_at: datetime
    duration_minutes: int
    status: AppointmentStatus
    reason: str | None
    notes: str | None


class AgendaQuery(BaseModel):
    date: date
    professional_id: int | None = None


class WeeklyAgendaQuery(BaseModel):
    week_start: date
    professional_id: int | None = None
