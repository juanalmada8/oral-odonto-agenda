from datetime import date

from sqlalchemy import Boolean, Date, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin


class Patient(TimestampMixin, Base):
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    dni: Mapped[str] = mapped_column(String(20), nullable=False, unique=True, index=True)
    first_name: Mapped[str] = mapped_column(String(80), nullable=False)
    last_name: Mapped[str] = mapped_column(String(80), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(40))
    observations: Mapped[str | None] = mapped_column(Text())

    # Ficha que carga el mostrador cuando el paciente viene por primera vez: la reserva
    # online solo pide lo mínimo para dar el turno.
    birth_date: Mapped[date | None] = mapped_column(Date())
    address: Mapped[str | None] = mapped_column(String(180))
    city: Mapped[str | None] = mapped_column(String(80))
    health_insurance: Mapped[str | None] = mapped_column(String(120))
    health_insurance_number: Mapped[str | None] = mapped_column(String(60))
    emergency_contact: Mapped[str | None] = mapped_column(String(160))
    medical_notes: Mapped[str | None] = mapped_column(Text())
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    appointments = relationship("Appointment", back_populates="patient")
    notifications = relationship("Notification", back_populates="patient")
