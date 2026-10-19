"""Follow-up service: patient and professional notifications through a retrying outbox.

Messages are stored as `Notification` rows and sent by `send_pending_notifications`, which runs
right after the request that queued them (background task) and periodically from the scheduled
job, so a provider outage only delays messages instead of losing them.
"""

import logging
from datetime import datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import Settings
from app.core.enums import AppointmentStatus, NotificationChannel, NotificationStatus, NotificationType
from app.integrations.email import EmailClient
from app.integrations.whatsapp import WhatsAppClient
from app.models.appointment import Appointment
from app.models.notification import Notification
from app.models.professional import Professional
from app.services.messages import MessageComposer
from app.utils.audit import create_audit_log

logger = logging.getLogger(__name__)

# Reminders go to appointments the patient is expected to attend.
REMINDABLE_STATUSES = (AppointmentStatus.RESERVED, AppointmentStatus.CONFIRMED)
INACTIVE_STATUSES = (AppointmentStatus.CANCELLED, AppointmentStatus.EXPIRED)
# What a professional has on the agenda: held (unpaid) slots are not an appointment yet.
AGENDA_STATUSES = REMINDABLE_STATUSES
RETRY_BASE_MINUTES = 5
# Patient emails that may carry the "confirm your appointment" button (spec 0005).
CONFIRMATION_REQUEST_TYPES = (NotificationType.REMINDER, NotificationType.CONFIRMATION, NotificationType.RESCHEDULE)


class FollowUpService:
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

    def asks_confirmation(self, appointment: Appointment) -> bool:
        """An unconfirmed appointment less than a day away: its email carries the confirm button (spec 0005)."""
        if appointment.status != AppointmentStatus.RESERVED or not appointment.notification_email:
            return False
        now = clock.now()
        return now < appointment.starts_at <= now + timedelta(hours=self.settings.reminder_hours_ahead)

    @staticmethod
    def _for_time(appointment: Appointment, asks_confirmation: bool) -> dict:
        """Ties a patient email to the time it talks about: once the appointment moves, it is stale."""
        return {"for_starts_at": appointment.starts_at.isoformat(), "asks_confirmation": asks_confirmation}

    # ------------------------------------------------------------------ queueing

    def queue_confirmation(self, db: Session, appointment: Appointment, actor: str = "followup_service") -> Notification | None:
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
        # Booked less than a day ahead: this email is also the request to confirm, no second one follows.
        asks = self.asks_confirmation(appointment)
        content = self.composer.confirmation(appointment, ask_to_confirm=asks)
        if existing:
            existing.recipient = recipient
            existing.subject, existing.body, existing.html_body = content.subject, content.text, content.html
            existing.payload = self._for_time(appointment, asks)
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
            payload=self._for_time(appointment, asks),
            actor=actor,
        )

    def queue_cancellation(self, db: Session, appointment: Appointment, actor: str = "followup_service") -> Notification | None:
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
        actor: str = "followup_service",
    ) -> Notification | None:
        """Tell the patient their appointment moved: otherwise they show up at the old time."""
        recipient = appointment.notification_email
        if not recipient:
            return None
        # Moved to less than a day ahead: the new time is confirmed from this email, with its own link.
        asks = self.asks_confirmation(appointment)
        content = self.composer.reschedule(appointment, previous_when=previous_when, ask_to_confirm=asks)
        return self._queue(
            db,
            appointment=appointment,
            type_=NotificationType.RESCHEDULE,
            channel=NotificationChannel.EMAIL,
            recipient=recipient,
            subject=content.subject,
            body=content.text,
            html_body=content.html,
            payload=self._for_time(appointment, asks),
            actor=actor,
        )

    def queue_waitlist_offer(self, db: Session, entry, appointment: Appointment, actor: str = "followup_service"):
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

    def queue_series(self, db: Session, appointments: list[Appointment], actor: str = "followup_service") -> Notification | None:
        """Confirma una serie completa en un mensaje, colgado del primer turno."""
        first = appointments[0]
        recipient = first.notification_email
        if not recipient:
            return None
        content = self.composer.series(appointments)
        return self._queue(
            db,
            appointment=first,
            type_=NotificationType.CONFIRMATION,
            channel=NotificationChannel.EMAIL,
            recipient=recipient,
            subject=content.subject,
            body=content.text,
            html_body=content.html,
            actor=actor,
        )

    # ------------------------------------------------------------ professional notices
    #
    # These go to the professional's own email (never to the patient) and carry no patient id, so they do
    # not show up in a patient's history. A professional without an email simply gets nothing.

    def queue_professional_booking(
        self, db: Session, appointments: Appointment | list[Appointment], actor: str = "followup_service"
    ) -> Notification | None:
        """A new appointment (or a whole series, in one message) landed on the professional's agenda."""
        items = [appointments] if isinstance(appointments, Appointment) else list(appointments)
        first = items[0]
        recipient = first.professional.email
        if not recipient:
            return None
        content = self.composer.professional_booking(items)
        return self._queue(
            db,
            appointment=first,
            type_=NotificationType.PROFESSIONAL_NEW,
            channel=NotificationChannel.EMAIL,
            recipient=recipient,
            subject=content.subject,
            body=content.text,
            html_body=content.html,
            payload={"appointment_ids": [item.id for item in items]},
            actor=actor,
            about_patient=False,
        )

    def queue_professional_cancellation(
        self, db: Session, appointment: Appointment, actor: str = "followup_service"
    ) -> Notification | None:
        recipient = appointment.professional.email
        if not recipient:
            return None
        # The professional never heard about this appointment: telling them it was cancelled is noise.
        unsent = self._pending_professional_booking(db, appointment)
        if unsent is not None:
            unsent.status = NotificationStatus.SKIPPED
            unsent.error_message = "El turno se canceló antes de avisarlo"
            return None
        content = self.composer.professional_cancellation(appointment)
        return self._queue(
            db,
            appointment=appointment,
            type_=NotificationType.PROFESSIONAL_CANCEL,
            channel=NotificationChannel.EMAIL,
            recipient=recipient,
            subject=content.subject,
            body=content.text,
            html_body=content.html,
            actor=actor,
            about_patient=False,
        )

    def queue_professional_reschedule(
        self,
        db: Session,
        appointment: Appointment,
        previous_when: str | None = None,
        actor: str = "followup_service",
    ) -> Notification | None:
        recipient = appointment.professional.email
        if not recipient:
            return None
        # "New appointment" has not gone out yet (e.g. the mail server was down): update that message
        # with the new time instead of sending a stale one followed by a correction.
        unsent = self._pending_professional_booking(db, appointment)
        if unsent is not None:
            content = self.composer.professional_booking([appointment])
            unsent.subject, unsent.body, unsent.html_body = content.subject, content.text, content.html
            unsent.scheduled_for = clock.now()
            return unsent
        content = self.composer.professional_reschedule(appointment, previous_when)
        return self._queue(
            db,
            appointment=appointment,
            type_=NotificationType.PROFESSIONAL_MOVE,
            channel=NotificationChannel.EMAIL,
            recipient=recipient,
            subject=content.subject,
            body=content.text,
            html_body=content.html,
            actor=actor,
            about_patient=False,
        )

    def prepare_unconfirmed_alerts(self, db: Session, *, actor: str = "followup_service") -> int:
        """Tell the professional which patients were asked to confirm and still have not (spec 0005).

        Only when the request went out at least `professional_unconfirmed_hours` before the
        appointment: someone booked late at night for the next morning had no time to answer.
        One alert per appointment and time. Nothing is ever cancelled.
        """
        hours = self.settings.professional_unconfirmed_hours
        now = clock.now()
        appointments = db.scalars(
            select(Appointment)
            .where(Appointment.status == AppointmentStatus.RESERVED)
            .where(Appointment.starts_at > now)
            .where(Appointment.starts_at <= now + timedelta(hours=hours))
            .order_by(Appointment.starts_at)
        ).all()
        created = 0
        for appointment in appointments:
            recipient = appointment.professional.email
            if not recipient:
                continue
            current = appointment.starts_at.isoformat()
            deadline = appointment.starts_at - timedelta(hours=hours)
            requests = db.execute(
                select(Notification.payload, Notification.sent_at)
                .where(Notification.appointment_id == appointment.id)
                .where(Notification.channel == NotificationChannel.EMAIL)
                .where(Notification.status == NotificationStatus.SENT)
                .where(Notification.type.in_(CONFIRMATION_REQUEST_TYPES))
            ).all()
            asked_in_time = any(
                (payload or {}).get("asks_confirmation")
                and payload.get("for_starts_at") == current
                and sent_at is not None
                and sent_at <= deadline
                for payload, sent_at in requests
            )
            if not asked_in_time:
                continue
            already = any(
                (payload or {}).get("for_starts_at") == current
                for (payload,) in db.execute(
                    select(Notification.payload)
                    .where(Notification.appointment_id == appointment.id)
                    .where(Notification.type == NotificationType.PROFESSIONAL_PENDING)
                )
            )
            if already:
                continue
            content = self.composer.professional_unconfirmed(appointment)
            self._queue(
                db,
                appointment=appointment,
                type_=NotificationType.PROFESSIONAL_PENDING,
                channel=NotificationChannel.EMAIL,
                recipient=recipient,
                subject=content.subject,
                body=content.text,
                html_body=content.html,
                payload={"for_starts_at": current},
                actor=actor,
                about_patient=False,
            )
            created += 1
        db.commit()
        return created

    def prepare_professional_digests(self, db: Session, *, actor: str = "followup_service") -> int:
        """Queue tomorrow's agenda for every professional that has appointments and an email.

        Runs on every scheduled tick but only acts from `professional_digest_hour`, once per
        professional and day, and never sends an empty agenda.
        """
        now = clock.now()
        if now.hour < self.settings.professional_digest_hour:
            return 0
        day = now.date() + timedelta(days=1)
        day_start = datetime.combine(day, time.min)
        # Any status counts as "already handled": a failed digest must not be regenerated every ten minutes.
        done = {
            payload.get("professional_id")
            for (payload,) in db.execute(
                select(Notification.payload)
                .where(Notification.type == NotificationType.PROFESSIONAL_DIGEST)
                .where(Notification.scheduled_for >= datetime.combine(now.date(), time.min))
            )
            if payload and payload.get("for_date") == day.isoformat()
        }
        professionals = db.scalars(
            select(Professional)
            .where(Professional.is_active.is_(True))
            .where(Professional.email.is_not(None))
            .where(Professional.email != "")
            .order_by(Professional.id)
        ).all()
        created = 0
        for professional in professionals:
            if professional.id in done:
                continue
            appointments = db.scalars(
                select(Appointment)
                .where(Appointment.professional_id == professional.id)
                .where(Appointment.status.in_(AGENDA_STATUSES))
                .where(Appointment.starts_at >= day_start)
                .where(Appointment.starts_at < day_start + timedelta(days=1))
                .order_by(Appointment.starts_at)
            ).all()
            if not appointments:
                continue
            content = self.composer.professional_digest(professional, day, list(appointments))
            self._queue(
                db,
                appointment=None,
                type_=NotificationType.PROFESSIONAL_DIGEST,
                channel=NotificationChannel.EMAIL,
                recipient=professional.email,
                subject=content.subject,
                body=content.text,
                html_body=content.html,
                payload={"professional_id": professional.id, "for_date": day.isoformat()},
                actor=actor,
                about_patient=False,
            )
            created += 1
        db.commit()
        return created

    def _pending_professional_booking(self, db: Session, appointment: Appointment) -> Notification | None:
        """The not-yet-sent "new appointment" notice that is about this appointment and only this one."""
        candidates = db.scalars(
            select(Notification)
            .where(Notification.appointment_id == appointment.id)
            .where(Notification.type == NotificationType.PROFESSIONAL_NEW)
            .where(Notification.status == NotificationStatus.PENDING)
            .order_by(Notification.id.desc())
        ).all()
        for notification in candidates:
            ids = (notification.payload or {}).get("appointment_ids")
            if ids in (None, [appointment.id]):
                return notification
        return None

    def prepare_upcoming_reminders(
        self,
        db: Session,
        *,
        hours_ahead: int | None = None,
        actor: str = "followup_service",
    ) -> int:
        """Queue email and WhatsApp reminders for appointments starting within `hours_ahead`.

        While the appointment is not confirmed, the email reminder is the request to confirm it.
        Reminders are tied to the appointment's time: one moved to another day is reminded again,
        and one whose booking or reschedule email already asked for confirmation is not.
        """
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
            current = appointment.starts_at.isoformat()
            already = set()
            for channel, type_, payload in db.execute(
                select(Notification.channel, Notification.type, Notification.payload)
                .where(Notification.appointment_id == appointment.id)
                .where(Notification.type.in_(CONFIRMATION_REQUEST_TYPES))
                .where(Notification.status != NotificationStatus.SKIPPED)
            ):
                payload = payload or {}
                # Reminders queued before they carried their time count as done for the current one.
                if type_ == NotificationType.REMINDER and payload.get("for_starts_at", current) == current:
                    already.add(channel)
                elif payload.get("asks_confirmation") and payload.get("for_starts_at") == current:
                    already.add(channel)
            if appointment.notification_email and NotificationChannel.EMAIL not in already:
                asks = self.asks_confirmation(appointment)
                content = self.composer.reminder(appointment, ask_to_confirm=asks)
                self._queue(
                    db,
                    appointment=appointment,
                    type_=NotificationType.REMINDER,
                    channel=NotificationChannel.EMAIL,
                    recipient=appointment.notification_email,
                    subject=content.subject,
                    body=content.text,
                    html_body=content.html,
                    payload=self._for_time(appointment, asks),
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
                    payload=message.as_payload() | {"for_starts_at": current},
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

    def send_pending_notifications(self, db: Session, *, limit: int = 50, actor: str = "followup_service") -> dict[str, int]:
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
        for_starts_at = (notification.payload or {}).get("for_starts_at")
        if appointment is not None and for_starts_at and for_starts_at != appointment.starts_at.isoformat():
            # Written for a time the appointment no longer has; a newer message covers the new one.
            return "El turno cambió de horario"
        if notification.type == NotificationType.PROFESSIONAL_PENDING:
            if appointment is not None and appointment.status == AppointmentStatus.CONFIRMED:
                return "El paciente ya confirmó"
            if appointment is None or appointment.status != AppointmentStatus.RESERVED:
                return "El turno ya no está activo"
            if appointment.starts_at <= now:
                return "El turno ya pasó"
        if notification.type == NotificationType.REMINDER:
            if appointment is None or appointment.status not in REMINDABLE_STATUSES:
                return "El turno ya no está activo"
            if appointment.starts_at <= now:
                return "El turno ya pasó"
        if notification.type == NotificationType.CONFIRMATION and appointment is not None:
            if appointment.status in INACTIVE_STATUSES:
                return "El turno ya no está activo"
        if notification.type in (NotificationType.PROFESSIONAL_NEW, NotificationType.PROFESSIONAL_MOVE):
            if appointment is not None and appointment.status in INACTIVE_STATUSES:
                return "El turno ya no está activo"
        return None

    def _queue(
        self,
        db: Session,
        *,
        appointment: Appointment | None,
        type_: NotificationType,
        channel: NotificationChannel,
        recipient: str,
        subject: str,
        body: str,
        actor: str,
        html_body: str | None = None,
        payload: dict | None = None,
        scheduled_for=None,
        about_patient: bool = True,
    ) -> Notification:
        notification = Notification(
            appointment_id=appointment.id if appointment is not None else None,
            patient_id=appointment.patient_id if appointment is not None and about_patient else None,
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
