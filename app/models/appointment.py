from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import AppointmentStatus
from app.db.base import Base
from app.models.mixins import TimestampMixin


class Appointment(TimestampMixin, Base):
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
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
        Enum(AppointmentStatus, name="appointment_status"),
        nullable=False,
        default=AppointmentStatus.RESERVED,
        server_default=AppointmentStatus.RESERVED.value,
    )
    reason: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text())
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    created_by: Mapped[str] = mapped_column(String(80), nullable=False, default="system", server_default="system")

    patient = relationship("Patient", back_populates="appointments")
    professional = relationship("Professional", back_populates="appointments")
    notifications = relationship("Notification", back_populates="appointment")
