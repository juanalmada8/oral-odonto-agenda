"""WhatsApp bot: handles patient replies to reminders (confirm attendance / cancel).

Reminder buttons carry "CONFIRM:<token>" / "CANCEL:<token>". Cancelling asks for a second tap
("CANCEL_OK" / "KEEP") so an accidental touch never frees a paid slot.
"""

import hashlib
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import Settings
from app.core.enums import AppointmentStatus, NotificationStatus
from app.core.exceptions import DomainError
from app.integrations.whatsapp import WhatsAppClient, WhatsAppError, same_whatsapp_number
from app.models.appointment import Appointment
from app.models.audit_log import AuditLog
from app.models.notification import Notification
from app.services.booking_service import BookingService
from app.services.messages import MessageComposer
from app.services.schedule_service import ScheduleService
from app.utils.audit import create_audit_log

logger = logging.getLogger(__name__)

INBOUND_ACTION = "whatsapp.inbound"


class WhatsAppBot:
    def __init__(
        self,
        settings: Settings,
        *,
        whatsapp_client: WhatsAppClient,
        booking_service: BookingService,
        schedule_service: ScheduleService,
    ) -> None:
        self.settings = settings
        self.whatsapp = whatsapp_client
        self.booking_service = booking_service
        self.schedule_service = schedule_service
        self.composer = MessageComposer(settings)

    def handle_webhook(self, db: Session, payload: dict) -> None:
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value") or {}
                for status in value.get("statuses", []):
                    self._handle_status(db, status)
                for message in value.get("messages", []):
                    try:
                        self._handle_message(db, message)
                    except Exception:
                        db.rollback()
                        logger.exception("Could not handle WhatsApp message %s", message.get("id"))

    # ------------------------------------------------------------------ messages

    def _handle_message(self, db: Session, message: dict) -> None:
        message_id = message.get("id") or ""
        sender = message.get("from") or ""
        fingerprint = hashlib.sha1(message_id.encode()).hexdigest()
        # Meta redelivers webhooks; answer each message once.
        if db.scalar(select(AuditLog.id).where(AuditLog.action == INBOUND_ACTION).where(AuditLog.entity_id == fingerprint)):
            return
        create_audit_log(
            db,
            action=INBOUND_ACTION,
            entity_name="whatsapp_message",
            entity_id=fingerprint,
            actor=f"whatsapp:{sender[-4:]}",
            description=f"Inbound {message.get('type')} message",
        )
        db.commit()

        action_payload = None
        if message.get("type") == "button":
            action_payload = (message.get("button") or {}).get("payload")
        elif message.get("type") == "interactive":
            action_payload = ((message.get("interactive") or {}).get("button_reply") or {}).get("id")

        if action_payload and ":" in action_payload:
            action, _, token = action_payload.partition(":")
            self._handle_action(db, sender=sender, action=action, token=token)
        else:
            self._reply(sender, self._help_text())

    def _handle_action(self, db: Session, *, sender: str, action: str, token: str) -> None:
        appointment = db.scalar(select(Appointment).where(Appointment.public_token == token[:64]))
        if appointment is None or not same_whatsapp_number(sender, appointment.notification_phone):
            logger.warning("WhatsApp action %s for unknown appointment or foreign number", action)
            self._reply(sender, self._help_text())
            return

        when = self.composer.when_text(appointment)
        professional = f"{appointment.professional.first_name} {appointment.professional.last_name}"
        active = appointment.status in {AppointmentStatus.RESERVED, AppointmentStatus.CONFIRMED}

        if action == "CONFIRM":
            if not active:
                self._reply(sender, f"Ese turno ya no está activo. Podés reservar uno nuevo en {self.settings.public_base_url}/reservar")
                return
            appointment.attendance_confirmed_at = clock.now()
            create_audit_log(
                db,
                action="appointment.attendance_confirmed",
                entity_name="appointment",
                entity_id=str(appointment.id),
                actor="patient:whatsapp",
                description="Patient confirmed attendance from WhatsApp",
            )
            db.commit()
            self._reply(sender, f"¡Gracias, {appointment.patient.first_name}! Te esperamos el {when} con {professional}.")
        elif action == "CANCEL":
            if not active:
                self._reply(sender, "Ese turno ya no está activo.")
                return
            self._buttons(
                sender,
                f"¿Querés cancelar tu turno del {when} con {professional}?",
                [(f"CANCEL_OK:{appointment.public_token}", "Sí, cancelar"), (f"KEEP:{appointment.public_token}", "No, mantener")],
            )
        elif action == "CANCEL_OK":
            try:
                self.booking_service.cancel_by_patient(db, appointment, channel="whatsapp")
            except DomainError as exc:
                db.rollback()
                self._reply(sender, exc.detail)
                return
            self._reply(
                sender,
                f"Listo, cancelamos tu turno del {when}. Si querés reservar otro: {self.settings.public_base_url}/reservar",
            )
        elif action == "KEEP":
            self._reply(sender, f"Perfecto, mantenemos tu turno del {when}. ¡Te esperamos!")
        else:
            self._reply(sender, self._help_text())

    # ------------------------------------------------------------------ delivery statuses

    def _handle_status(self, db: Session, status: dict) -> None:
        if status.get("status") != "failed":
            return
        notification = db.scalar(select(Notification).where(Notification.provider_message_id == status.get("id")))
        if notification is None:
            return
        error = (status.get("errors") or [{}])[0]
        notification.status = NotificationStatus.FAILED
        notification.error_message = f"WhatsApp: {error.get('title') or error.get('message') or 'entrega fallida'}"
        db.commit()

    # ------------------------------------------------------------------ replies

    def _help_text(self) -> str:
        contact = f" o llamanos al {self.settings.clinic_phone}" if self.settings.clinic_phone else ""
        return (
            f"Hola, este es el canal automático de recordatorios de {self.settings.clinic_name}. "
            f"Para reservar o gestionar un turno ingresá a {self.settings.public_base_url}/reservar{contact}."
        )

    def _reply(self, to: str, body: str) -> None:
        try:
            self.whatsapp.send_text(to=to, body=body)
        except WhatsAppError as exc:
            logger.error("WhatsApp reply to %s failed: %s", to[-4:], exc)

    def _buttons(self, to: str, body: str, buttons: list[tuple[str, str]]) -> None:
        try:
            self.whatsapp.send_buttons(to=to, body=body, buttons=buttons)
        except WhatsAppError as exc:
            logger.error("WhatsApp buttons to %s failed: %s", to[-4:], exc)
