from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin


class Professional(TimestampMixin, Base):
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    first_name: Mapped[str] = mapped_column(String(80), nullable=False)
    last_name: Mapped[str] = mapped_column(String(80), nullable=False)
    specialty: Mapped[str | None] = mapped_column(String(120))
    email: Mapped[str | None] = mapped_column(String(255), unique=True)
    phone: Mapped[str | None] = mapped_column(String(40), unique=True)
    default_appointment_duration: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=30,
        server_default="30",
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    appointments = relationship("Appointment", back_populates="professional")
    availability_windows = relationship("AvailabilityWindow", back_populates="professional", cascade="all, delete-orphan")
    working_hours = relationship("WorkingHours", back_populates="professional", cascade="all, delete-orphan")
    holiday_blocks = relationship("HolidayBlock", back_populates="professional")
