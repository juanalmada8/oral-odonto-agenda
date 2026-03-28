from datetime import datetime

from pydantic import BaseModel, Field

from app.core.enums import NotificationChannel, NotificationStatus, NotificationType
from app.schemas.common import TimestampedModel


class NotificationCreate(BaseModel):
    appointment_id: int | None = None
    patient_id: int | None = None
    type: NotificationType = NotificationType.CUSTOM
    channel: NotificationChannel = NotificationChannel.EMAIL
    recipient: str = Field(..., max_length=255)
    subject: str = Field(..., max_length=255)
    body: str
    scheduled_for: datetime


class NotificationRead(TimestampedModel):
    appointment_id: int | None
    patient_id: int | None
    type: NotificationType
    channel: NotificationChannel
    recipient: str
    subject: str
    body: str
    scheduled_for: datetime
    sent_at: datetime | None
    status: NotificationStatus
    error_message: str | None


class ReminderBatchResult(BaseModel):
    prepared: int
    sent: int
    skipped: int
