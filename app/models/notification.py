from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import NotificationChannel, NotificationStatus, NotificationType
from app.db.base import Base
from app.models.mixins import TimestampMixin


class Notification(TimestampMixin, Base):
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    appointment_id: Mapped[int | None] = mapped_column(ForeignKey("appointment.id", ondelete="SET NULL"), index=True)
    patient_id: Mapped[int | None] = mapped_column(ForeignKey("patient.id", ondelete="SET NULL"), index=True)
    type: Mapped[NotificationType] = mapped_column(Enum(NotificationType, name="notification_type"), nullable=False)
    channel: Mapped[NotificationChannel] = mapped_column(
        Enum(NotificationChannel, name="notification_channel"),
        nullable=False,
        default=NotificationChannel.EMAIL,
        server_default=NotificationChannel.EMAIL.value,
    )
    recipient: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text(), nullable=False)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    status: Mapped[NotificationStatus] = mapped_column(
        Enum(NotificationStatus, name="notification_status"),
        nullable=False,
        default=NotificationStatus.PENDING,
        server_default=NotificationStatus.PENDING.value,
    )
    error_message: Mapped[str | None] = mapped_column(Text())

    appointment = relationship("Appointment", back_populates="notifications")
    patient = relationship("Patient", back_populates="notifications")
