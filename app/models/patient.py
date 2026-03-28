from sqlalchemy import Boolean, String, Text
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
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    appointments = relationship("Appointment", back_populates="patient")
    notifications = relationship("Notification", back_populates="patient")
