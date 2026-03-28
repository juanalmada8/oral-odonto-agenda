from datetime import time

from sqlalchemy import ForeignKey, Integer, Time
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin


class WorkingHours(TimestampMixin, Base):
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    professional_id: Mapped[int] = mapped_column(ForeignKey("professional.id", ondelete="CASCADE"), nullable=False)
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    slot_duration_minutes: Mapped[int | None] = mapped_column(Integer)

    professional = relationship("Professional", back_populates="working_hours")
