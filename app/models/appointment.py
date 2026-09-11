import secrets
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import AppointmentStatus
from app.db.base import Base
from app.db.types import enum_column
from app.models.mixins import TimestampMixin


def generate_public_token() -> str:
    return secrets.token_urlsafe(24)


class Appointment(TimestampMixin, Base):
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    # Unguessable id used in patient-facing links; never expose the sequential primary key.
    public_token: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
        index=True,
        default=generate_public_token,
    )
    patient_id: Mapped[int] = mapped_column(ForeignKey("patient.id", ondelete="RESTRICT"), nullable=False, index=True)
    professional_id: Mapped[int] = mapped_column(
        ForeignKey("professional.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[AppointmentStatus] = mapped_column(
        enum_column(AppointmentStatus),
        nullable=False,
        default=AppointmentStatus.RESERVED,
        server_default=AppointmentStatus.RESERVED.value,
    )
    reason: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text())
    # Contact given for this booking. Public bookings never overwrite the patient master record,
    # so notifications for the appointment go here first.
    contact_email: Mapped[str | None] = mapped_column(String(255))
    contact_phone: Mapped[str | None] = mapped_column(String(40))
    # While the deposit is unpaid the slot is held until this moment, then released.
    hold_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    created_by: Mapped[str] = mapped_column(String(80), nullable=False, default="system", server_default="system")

    patient = relationship("Patient", back_populates="appointments")
    professional = relationship("Professional", back_populates="appointments")
    notifications = relationship("Notification", back_populates="appointment")

    @property
    def notification_email(self) -> str | None:
        return self.contact_email or (self.patient.email if self.patient else None)

    @property
    def notification_phone(self) -> str | None:
        return self.contact_phone or (self.patient.phone if self.patient else None)
