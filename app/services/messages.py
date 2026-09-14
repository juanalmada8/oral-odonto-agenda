"""Patient-facing message content (emails and WhatsApp), rendered from app/templates/emails."""

from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from app.core.config import Settings
from app.core.enums import AppointmentStatus, PaymentStatus
from app.models.appointment import Appointment
from app.utils.formatting import format_long_date, format_money

EMAIL_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates" / "emails"


@dataclass(frozen=True)
class EmailContent:
    subject: str
    text: str
    html: str


@dataclass(frozen=True)
class WhatsAppTemplateContent:
    template: str
    language: str
    body_params: list[str]
    button_payloads: list[str]
    preview: str

    def as_payload(self) -> dict:
        return {
            "kind": "template",
            "template": self.template,
            "language": self.language,
            "body_params": self.body_params,
            "button_payloads": self.button_payloads,
        }


class MessageComposer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        # Autoescape only the HTML parts: the plain-text version must keep "O'Connor" as typed.
        self.env = Environment(
            loader=FileSystemLoader(EMAIL_TEMPLATES_DIR),
            autoescape=select_autoescape(["html"]),
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self.env.filters["money"] = format_money

    def confirmation(self, appointment: Appointment) -> EmailContent:
        context = self._context(appointment)
        if appointment.status == AppointmentStatus.CONFIRMED:
            subject = f"Turno confirmado: {context['when_short']}"
        else:
            subject = f"Turno reservado: {context['when_short']}"
        return self._render("confirmation", subject, context)

    def reminder(self, appointment: Appointment) -> EmailContent:
        context = self._context(appointment)
        return self._render("reminder", f"Recordatorio de tu turno: {context['when_short']}", context)

    def cancellation(self, appointment: Appointment) -> EmailContent:
        context = self._context(appointment)
        return self._render("cancellation", f"Turno cancelado: {context['when_short']}", context)

    def waitlist_offer(self, appointment: Appointment, patient_first_name: str) -> EmailContent:
        """El turno es de otro paciente: el nombre viene de quien está en la lista."""
        context = self._context(appointment) | {"patient_first_name": patient_first_name}
        return self._render("waitlist", f"Se liberó un turno: {context['when_short']}", context)

    def reschedule(self, appointment: Appointment, previous_when: str | None = None) -> EmailContent:
        """`previous_when` is the old date in words, so the patient sees what changed."""
        context = self._context(appointment) | {"previous_when": previous_when}
        return self._render("reschedule", f"Cambiamos tu turno: ahora {context['when_short']}", context)

    def whatsapp_reminder(self, appointment: Appointment) -> WhatsAppTemplateContent:
        context = self._context(appointment)
        params = [
            appointment.patient.first_name,
            context["date_long"],
            context["time"],
            context["professional_name"],
        ]
        return WhatsAppTemplateContent(
            template=self.settings.whatsapp_reminder_template,
            language=self.settings.whatsapp_template_language,
            body_params=params,
            button_payloads=[f"CONFIRM:{appointment.public_token}", f"CANCEL:{appointment.public_token}"],
            preview=(
                f"Hola {params[0]}, te recordamos tu turno en {self.settings.clinic_name} el {params[1]} "
                f"a las {params[2]} h con {params[3]}. ¿Confirmás tu asistencia? [Confirmo asistencia] [Necesito cancelar]"
            ),
        )

    def when_text(self, appointment: Appointment) -> str:
        return f"{format_long_date(appointment.starts_at)} a las {appointment.starts_at:%H:%M} h"

    def _context(self, appointment: Appointment) -> dict:
        base_url = self.settings.public_base_url
        professional = appointment.professional
        payment = appointment.latest_payment
        return {
            "clinic_name": self.settings.clinic_name,
            "clinic_address": self.settings.clinic_address,
            "clinic_phone": self.settings.clinic_phone,
            # Resolved against the image the EmailClient embeds in the message itself.
            "logo_url": "cid:oral-logo",
            "booking_url": f"{base_url}/reservar",
            "status_url": f"{base_url}/reservar/turno/{appointment.public_token}",
            "calendar_url": f"{base_url}/reservar/turno/{appointment.public_token}/calendario.ics",
            "patient_first_name": appointment.patient.first_name,
            "professional_name": f"{professional.first_name} {professional.last_name}",
            "specialty": professional.specialty,
            "date_long": format_long_date(appointment.starts_at),
            "date_long_capitalized": format_long_date(appointment.starts_at).capitalize(),
            "when_short": f"{appointment.starts_at:%d/%m} {appointment.starts_at:%H:%M} h",
            "time": appointment.starts_at.strftime("%H:%M"),
            "end_time": appointment.ends_at.strftime("%H:%M"),
            "status": appointment.status.value,
            "deposit_paid": (
                payment.amount if payment is not None and payment.status == PaymentStatus.APPROVED else None
            ),
            "deposit_policy": self.settings.deposit_policy,
            "cancellation_notice_hours": self.settings.cancellation_notice_hours,
        }

    def _render(self, name: str, subject: str, context: dict) -> EmailContent:
        context = {**context, "subject": subject}
        return EmailContent(
            subject=subject,
            text=self.env.get_template(f"{name}.txt").render(context).strip() + "\n",
            html=self.env.get_template(f"{name}.html").render(context),
        )
