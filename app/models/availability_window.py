from datetime import date, time

from sqlalchemy import Date, ForeignKey, Integer, Text, Time
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin


class AvailabilityWindow(TimestampMixin, Base):
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    professional_id: Mapped[int] = mapped_column(ForeignKey("professional.id", ondelete="CASCADE"), nullable=False)
    availability_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    slot_duration_minutes: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text())

    professional = relationship("Professional", back_populates="availability_windows")
