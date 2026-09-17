from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import NotificationChannel, NotificationStatus, NotificationType
from app.db.base import Base
from app.db.types import enum_column
from app.models.mixins import TimestampMixin


class Notification(TimestampMixin, Base):
    # The dispatcher polls "pending and due" rows.
    __table_args__ = (Index("ix_notification_status_scheduled_for", "status", "scheduled_for"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    appointment_id: Mapped[int | None] = mapped_column(ForeignKey("appointment.id", ondelete="SET NULL"), index=True)
    patient_id: Mapped[int | None] = mapped_column(ForeignKey("patient.id", ondelete="SET NULL"), index=True)
    type: Mapped[NotificationType] = mapped_column(enum_column(NotificationType), nullable=False)
    channel: Mapped[NotificationChannel] = mapped_column(
        enum_column(NotificationChannel),
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
        enum_column(NotificationStatus),
        nullable=False,
        default=NotificationStatus.PENDING,
        server_default=NotificationStatus.PENDING.value,
    )
    error_message: Mapped[str | None] = mapped_column(Text())
    html_body: Mapped[str | None] = mapped_column(Text())
    # Channel-specific data needed to send it again (e.g. WhatsApp template parameters).
    payload: Mapped[dict | None] = mapped_column(JSON)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    # Id returned by the provider (WhatsApp wamid), used to match delivery status updates.
    provider_message_id: Mapped[str | None] = mapped_column(String(128), index=True)

    appointment = relationship("Appointment", back_populates="notifications")
    patient = relationship("Patient", back_populates="notifications")
