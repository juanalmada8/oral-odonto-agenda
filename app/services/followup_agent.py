"""Follow-up agent: confirmations, reminders, and outbound notification queue."""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.enums import AppointmentStatus, NotificationChannel, NotificationStatus, NotificationType
from app.integrations.email import EmailClient
from app.models.appointment import Appointment
from app.models.notification import Notification
from app.utils.audit import create_audit_log


class FollowUpAgent:
    def __init__(self, settings: Settings, email_client: EmailClient) -> None:
        self.settings = settings
        self.email_client = email_client

    def list_notifications(self, db: Session) -> list[Notification]:
        return list(db.scalars(select(Notification).order_by(Notification.scheduled_for.desc())))

    def queue_confirmation(self, db: Session, appointment: Appointment, actor: str = "followup_agent") -> Notification | None:
        if not appointment.patient.email:
            return None
        now = datetime.now().replace(microsecond=0)
        existing_confirmation = db.scalar(
            select(Notification)
            .where(Notification.appointment_id == appointment.id)
            .where(Notification.type == NotificationType.CONFIRMATION)
            .where(Notification.channel == NotificationChannel.EMAIL)
            .order_by(Notification.id.desc())
        )
        subject = "Confirmacion de turno odontologico"
        body = (
            f"Hola {appointment.patient.first_name}, tu turno con "
            f"{appointment.professional.first_name} {appointment.professional.last_name} "
            f"quedo reservado para {appointment.starts_at:%Y-%m-%d %H:%M}."
        )

        if existing_confirmation:
            if existing_confirmation.status == NotificationStatus.SENT:
                return existing_confirmation
            existing_confirmation.recipient = appointment.patient.email
            existing_confirmation.subject = subject
            existing_confirmation.body = body
            existing_confirmation.scheduled_for = now
            existing_confirmation.sent_at = None
            existing_confirmation.error_message = None
            existing_confirmation.status = NotificationStatus.PENDING
            self._dispatch_notification(now, existing_confirmation)
            return existing_confirmation

        notification = self._queue_notification(
            db,
            appointment=appointment,
            type_=NotificationType.CONFIRMATION,
            recipient=appointment.patient.email,
            subject=subject,
            body=body,
            scheduled_for=now,
            actor=actor,
        )
        self._dispatch_notification(now, notification)
        return notification

    def prepare_upcoming_reminders(
        self,
        db: Session,
        *,
        hours_ahead: int | None = None,
        actor: str = "followup_agent",
    ) -> int:
        hours = hours_ahead or self.settings.reminder_hours_ahead
        now = datetime.now().replace(microsecond=0)
        deadline = now + timedelta(hours=hours)
        appointments = db.scalars(
            select(Appointment)
            .where(Appointment.status == AppointmentStatus.CONFIRMED)
            .where(Appointment.starts_at >= now)
            .where(Appointment.starts_at <= deadline)
        ).all()

        created = 0
        for appointment in appointments:
            if not appointment.patient.email:
                continue
            existing = db.scalar(
                select(Notification)
                .where(Notification.appointment_id == appointment.id)
                .where(Notification.type == NotificationType.REMINDER)
                .where(Notification.channel == NotificationChannel.EMAIL)
            )
            if existing:
                continue
            self._queue_notification(
                db,
                appointment=appointment,
                type_=NotificationType.REMINDER,
                recipient=appointment.patient.email,
                subject="Recordatorio de turno odontologico",
                body=(
                    f"Hola {appointment.patient.first_name}, te recordamos tu turno el "
                    f"{appointment.starts_at:%Y-%m-%d %H:%M} con "
                    f"{appointment.professional.first_name} {appointment.professional.last_name}."
                ),
                scheduled_for=max(now, appointment.starts_at - timedelta(hours=hours)),
                actor=actor,
            )
            created += 1

        db.commit()
        return created

    def send_pending_notifications(self, db: Session, *, limit: int = 20, actor: str = "followup_agent") -> dict[str, int]:
        now = datetime.now().replace(microsecond=0)
        pending = list(
            db.scalars(
                select(Notification)
                .where(Notification.status == NotificationStatus.PENDING)
                .where(Notification.scheduled_for <= now)
                .order_by(Notification.scheduled_for)
                .limit(limit)
            )
        )

        result = {"sent": 0, "skipped": 0}
        for notification in pending:
            if notification.type == NotificationType.CONFIRMATION:
                notification.status = NotificationStatus.SKIPPED
                notification.error_message = "Confirmation notifications are sent immediately"
                result["skipped"] += 1
                continue

            if notification.appointment_id and (
                not notification.appointment or notification.appointment.status != AppointmentStatus.CONFIRMED
            ):
                notification.status = NotificationStatus.SKIPPED
                notification.error_message = "Appointment is not confirmed"
                result["skipped"] += 1
                continue

            if notification.channel != NotificationChannel.EMAIL:
                notification.status = NotificationStatus.SKIPPED
                notification.error_message = "Channel not implemented yet"
                result["skipped"] += 1
                continue

            if not self.email_client.is_configured():
                notification.status = NotificationStatus.SKIPPED
                notification.error_message = "SMTP not configured"
                result["skipped"] += 1
                continue

            try:
                sent = self._dispatch_notification(now, notification)
                if sent:
                    result["sent"] += 1
                else:
                    result["skipped"] += 1
            except Exception as exc:  # pragma: no cover - network failures depend on environment
                notification.status = NotificationStatus.FAILED
                notification.error_message = str(exc)

        create_audit_log(
            db,
            action="notifications.dispatched",
            entity_name="notification_batch",
            entity_id=now.isoformat(),
            actor=actor,
            description="Pending notifications processed",
            details=result,
        )
        db.commit()
        return result

    def create_notification(self, db: Session, notification: Notification, actor: str = "followup_agent") -> Notification:
        db.add(notification)
        db.flush()
        create_audit_log(
            db,
            action="notification.created",
            entity_name="notification",
            entity_id=str(notification.id),
            actor=actor,
            description="Notification queued",
        )
        return notification

    def _queue_notification(
        self,
        db: Session,
        *,
        appointment: Appointment,
        type_: NotificationType,
        recipient: str,
        subject: str,
        body: str,
        scheduled_for: datetime,
        actor: str,
    ) -> Notification:
        notification = Notification(
            appointment_id=appointment.id,
            patient_id=appointment.patient_id,
            type=type_,
            channel=NotificationChannel.EMAIL,
            recipient=recipient,
            subject=subject,
            body=body,
            scheduled_for=scheduled_for,
        )
        self.create_notification(db, notification, actor=actor)
        return notification

    def _dispatch_notification(self, now: datetime, notification: Notification) -> bool:
        if notification.channel != NotificationChannel.EMAIL:
            notification.status = NotificationStatus.SKIPPED
            notification.error_message = "Channel not implemented yet"
            return False
        if not self.email_client.is_configured():
            notification.status = NotificationStatus.SKIPPED
            notification.error_message = "SMTP not configured"
            return False
        try:
            self.email_client.send_email(
                recipient=notification.recipient,
                subject=notification.subject,
                body=notification.body,
            )
            notification.status = NotificationStatus.SENT
            notification.sent_at = now
            notification.error_message = None
            return True
        except Exception as exc:  # pragma: no cover - network failures depend on environment
            notification.status = NotificationStatus.FAILED
            notification.error_message = str(exc)
            return False
