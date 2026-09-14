"""Follow-up agent: patient notifications (email + WhatsApp) through a retrying outbox.

Messages are stored as `Notification` rows and sent by `send_pending_notifications`, which runs
right after the request that queued them (background task) and periodically from the scheduled
job, so a provider outage only delays messages instead of losing them.
"""

import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import Settings
from app.core.enums import AppointmentStatus, NotificationChannel, NotificationStatus, NotificationType
from app.integrations.email import EmailClient
from app.integrations.whatsapp import WhatsAppClient
from app.models.appointment import Appointment
from app.models.notification import Notification
from app.services.messages import MessageComposer
from app.utils.audit import create_audit_log

logger = logging.getLogger(__name__)

# Reminders go to appointments the patient is expected to attend.
REMINDABLE_STATUSES = (AppointmentStatus.RESERVED, AppointmentStatus.CONFIRMED)
INACTIVE_STATUSES = (AppointmentStatus.CANCELLED, AppointmentStatus.EXPIRED)
RETRY_BASE_MINUTES = 5


class FollowUpAgent:
    def __init__(
        self,
        settings: Settings,
        email_client: EmailClient,
        whatsapp_client: WhatsAppClient | None = None,
        composer: MessageComposer | None = None,
    ) -> None:
        self.settings = settings
        self.email_client = email_client
        self.whatsapp_client = whatsapp_client or WhatsAppClient(settings)
        self.composer = composer or MessageComposer(settings)

    # ------------------------------------------------------------------ queries

    def list_notifications(self, db: Session, *, limit: int = 300) -> list[Notification]:
        return list(db.scalars(select(Notification).order_by(Notification.scheduled_for.desc()).limit(limit)))

    # ------------------------------------------------------------------ queueing

    def queue_confirmation(self, db: Session, appointment: Appointment, actor: str = "followup_agent") -> Notification | None:
        """One confirmation email per appointment; a pending one is refreshed instead of duplicated."""
        recipient = appointment.notification_email
        if not recipient:
            return None
        existing = db.scalar(
            select(Notification)
            .where(Notification.appointment_id == appointment.id)
            .where(Notification.type == NotificationType.CONFIRMATION)
            .where(Notification.channel == NotificationChannel.EMAIL)
            .where(Notification.status.in_([NotificationStatus.PENDING, NotificationStatus.SENT]))
            .order_by(Notification.id.desc())
        )
        if existing and existing.status == NotificationStatus.SENT:
            return existing
        content = self.composer.confirmation(appointment)
        if existing:
            existing.recipient = recipient
            existing.subject, existing.body, existing.html_body = content.subject, content.text, content.html
            existing.scheduled_for = clock.now()
            return existing
        return self._queue(
            db,
            appointment=appointment,
            type_=NotificationType.CONFIRMATION,
            channel=NotificationChannel.EMAIL,
            recipient=recipient,
            subject=content.subject,
            body=content.text,
            html_body=content.html,
            actor=actor,
        )

    def queue_cancellation(self, db: Session, appointment: Appointment, actor: str = "followup_agent") -> Notification | None:
        recipient = appointment.notification_email
        if not recipient:
            return None
        content = self.composer.cancellation(appointment)
        return self._queue(
            db,
            appointment=appointment,
            type_=NotificationType.CANCELLATION,
            channel=NotificationChannel.EMAIL,
            recipient=recipient,
            subject=content.subject,
            body=content.text,
            html_body=content.html,
            actor=actor,
        )

    def queue_reschedule(
        self,
        db: Session,
        appointment: Appointment,
        previous_when: str | None = None,
        actor: str = "followup_agent",
    ) -> Notification | None:
        """Tell the patient their appointment moved: otherwise they show up at the old time."""
        recipient = appointment.notification_email
        if not recipient:
            return None
        content = self.composer.reschedule(appointment, previous_when=previous_when)
        return self._queue(
            db,
            appointment=appointment,
            type_=NotificationType.RESCHEDULE,
            channel=NotificationChannel.EMAIL,
            recipient=recipient,
            subject=content.subject,
            body=content.text,
            html_body=content.html,
            actor=actor,
        )

    def queue_waitlist_offer(self, db: Session, entry, appointment: Appointment, actor: str = "followup_agent"):
        """Le ofrece a alguien de la lista de espera un horario que se liberó.

        La notificación se cuelga del turno liberado solo como referencia: el horario no
        queda reservado para esta persona.
        """
        recipient = entry.contact_email or entry.patient.email
        if not recipient:
            return None
        content = self.composer.waitlist_offer(appointment, entry.patient.first_name)
        return self._queue(
            db,
            appointment=appointment,
            type_=NotificationType.WAITLIST,
            channel=NotificationChannel.EMAIL,
            recipient=recipient,
            subject=content.subject,
            body=content.text,
            html_body=content.html,
            actor=actor,
        )

    def prepare_upcoming_reminders(
        self,
        db: Session,
        *,
        hours_ahead: int | None = None,
        actor: str = "followup_agent",
    ) -> int:
        """Queue email and WhatsApp reminders for appointments starting within `hours_ahead`."""
        hours = hours_ahead or self.settings.reminder_hours_ahead
        now = clock.now()
        appointments = db.scalars(
            select(Appointment)
            .where(Appointment.status.in_(REMINDABLE_STATUSES))
            .where(Appointment.starts_at > now)
            .where(Appointment.starts_at <= now + timedelta(hours=hours))
            .order_by(Appointment.starts_at)
        ).all()

        created = 0
        for appointment in appointments:
            scheduled_for = max(now, appointment.starts_at - timedelta(hours=hours))
            already = {
                channel
                for (channel,) in db.execute(
                    select(Notification.channel)
                    .where(Notification.appointment_id == appointment.id)
                    .where(Notification.type == NotificationType.REMINDER)
                    .where(Notification.status != NotificationStatus.SKIPPED)
                )
            }
            if appointment.notification_email and NotificationChannel.EMAIL not in already:
                content = self.composer.reminder(appointment)
                self._queue(
                    db,
                    appointment=appointment,
                    type_=NotificationType.REMINDER,
                    channel=NotificationChannel.EMAIL,
                    recipient=appointment.notification_email,
                    subject=content.subject,
                    body=content.text,
                    html_body=content.html,
                    scheduled_for=scheduled_for,
                    actor=actor,
                )
                created += 1
            if (
                appointment.notification_phone
                and self.whatsapp_client.is_configured()
                and NotificationChannel.WHATSAPP not in already
            ):
                message = self.composer.whatsapp_reminder(appointment)
                self._queue(
                    db,
                    appointment=appointment,
                    type_=NotificationType.REMINDER,
                    channel=NotificationChannel.WHATSAPP,
                    recipient=appointment.notification_phone,
                    subject="Recordatorio por WhatsApp",
                    body=message.preview,
                    payload=message.as_payload(),
                    scheduled_for=scheduled_for,
                    actor=actor,
                )
                created += 1
        db.commit()
        return created

    def discard_pending_reminders(self, db: Session, appointment: Appointment) -> int:
        """Skip reminders queued for an appointment that was cancelled or moved."""
        pending = db.scalars(
            select(Notification)
            .where(Notification.appointment_id == appointment.id)
            .where(Notification.type == NotificationType.REMINDER)
            .where(Notification.status == NotificationStatus.PENDING)
        ).all()
        for notification in pending:
            notification.status = NotificationStatus.SKIPPED
            notification.error_message = "El turno cambió o fue cancelado"
        return len(pending)

    # ------------------------------------------------------------------ sending

    def send_pending_notifications(self, db: Session, *, limit: int = 50, actor: str = "followup_agent") -> dict[str, int]:
        due_ids = list(
            db.scalars(
                select(Notification.id)
                .where(Notification.status == NotificationStatus.PENDING)
                .where(Notification.scheduled_for <= clock.now())
                .order_by(Notification.scheduled_for, Notification.id)
                .limit(limit)
            )
        )
        result = {"sent": 0, "skipped": 0, "failed": 0, "retrying": 0}
        for notification_id in due_ids:
            outcome = self.dispatch(db, notification_id)
            if outcome in result:
                result[outcome] += 1
        if due_ids:
            create_audit_log(
                db,
                action="notifications.dispatched",
                entity_name="notification_batch",
                entity_id=clock.now().isoformat(),
                actor=actor,
                description="Pending notifications processed",
                details=result,
            )
            db.commit()
        return result

    def dispatch(self, db: Session, notification_id: int) -> str:
        """Send one notification. Row-locked so concurrent dispatchers never send it twice."""
        notification = db.scalar(
            select(Notification)
            .where(Notification.id == notification_id)
            .where(Notification.status == NotificationStatus.PENDING)
            .with_for_update(skip_locked=True)
        )
        if notification is None:
            db.rollback()
            return "locked"

        now = clock.now()
        skip_reason = self._skip_reason(notification, now)
        if skip_reason:
            notification.status = NotificationStatus.SKIPPED
            notification.error_message = skip_reason
            db.commit()
            return "skipped"

        notification.attempts += 1
        notification.last_attempt_at = now
        try:
            notification.provider_message_id = self._send(notification)
        except Exception as exc:  # provider/network failures: retry with backoff
            logger.warning("Notification %s attempt %s failed: %s", notification.id, notification.attempts, exc)
            notification.error_message = str(exc)[:1000]
            if notification.attempts >= self.settings.notification_max_attempts:
                notification.status = NotificationStatus.FAILED
                db.commit()
                return "failed"
            notification.scheduled_for = now + timedelta(minutes=RETRY_BASE_MINUTES * 2 ** (notification.attempts - 1))
            db.commit()
            return "retrying"
        notification.status = NotificationStatus.SENT
        notification.sent_at = now
        notification.error_message = None
        db.commit()
        return "sent"

    def _send(self, notification: Notification) -> str | None:
        if notification.channel == NotificationChannel.EMAIL:
            return self.email_client.send_email(
                recipient=notification.recipient,
                subject=notification.subject,
                body=notification.body,
                html=notification.html_body,
            )
        payload = notification.payload or {}
        if payload.get("kind") == "template":
            return self.whatsapp_client.send_template(
                to=notification.recipient,
                template=payload["template"],
                language=payload["language"],
                body_params=payload["body_params"],
                button_payloads=payload.get("button_payloads"),
            )
        return self.whatsapp_client.send_text(to=notification.recipient, body=notification.body)

    def _skip_reason(self, notification: Notification, now) -> str | None:
        if notification.channel == NotificationChannel.EMAIL and not self.email_client.is_configured():
            return "SMTP no configurado"
        if notification.channel == NotificationChannel.WHATSAPP and not self.whatsapp_client.is_configured():
            return "WhatsApp no configurado"
        appointment = notification.appointment
        if notification.type == NotificationType.REMINDER:
            if appointment is None or appointment.status not in REMINDABLE_STATUSES:
                return "El turno ya no está activo"
            if appointment.starts_at <= now:
                return "El turno ya pasó"
        if notification.type == NotificationType.CONFIRMATION and appointment is not None:
            if appointment.status in INACTIVE_STATUSES:
                return "El turno ya no está activo"
        return None

    def _queue(
        self,
        db: Session,
        *,
        appointment: Appointment,
        type_: NotificationType,
        channel: NotificationChannel,
        recipient: str,
        subject: str,
        body: str,
        actor: str,
        html_body: str | None = None,
        payload: dict | None = None,
        scheduled_for=None,
    ) -> Notification:
        notification = Notification(
            appointment_id=appointment.id,
            patient_id=appointment.patient_id,
            type=type_,
            channel=channel,
            recipient=recipient,
            subject=subject,
            body=body,
            html_body=html_body,
            payload=payload,
            scheduled_for=scheduled_for or clock.now(),
        )
        db.add(notification)
        db.flush()
        create_audit_log(
            db,
            action="notification.created",
            entity_name="notification",
            entity_id=str(notification.id),
            actor=actor,
            description=f"{type_.value} queued via {channel.value}",
        )
        return notification
