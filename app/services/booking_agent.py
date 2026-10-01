"""Booking agent: a patient's self-service booking from /reservar, deposit included."""

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import Settings
from app.core.enums import AppointmentStatus
from app.core.exceptions import DomainError
from app.models.appointment import Appointment
from app.models.patient import Patient
from app.models.payment import Payment
from app.models.professional import Professional
from app.schemas.booking import PublicBookingRequest
from app.services.followup_agent import FollowUpAgent
from app.services.payment_service import PaymentService
from app.services.reception_agent import ReceptionAgent
from app.services.schedule_agent import SLOT_TAKEN_MESSAGE, ScheduleAgent
from app.services.waitlist_service import WaitlistService
from app.utils.audit import create_audit_log
from app.utils.datetime import ensure_local_naive

PUBLIC_ACTOR = "public_booking"


@dataclass
class BookingResult:
    appointment: Appointment
    payment: Payment | None = None
    checkout_error: str | None = None

    @property
    def checkout_url(self) -> str | None:
        return self.payment.checkout_url if self.payment else None


class BookingAgent:
    def __init__(
        self,
        settings: Settings,
        *,
        schedule_agent: ScheduleAgent,
        reception_agent: ReceptionAgent,
        followup_agent: FollowUpAgent,
        payment_service: PaymentService,
    ) -> None:
        self.settings = settings
        self.schedule_agent = schedule_agent
        self.reception_agent = reception_agent
        self.followup_agent = followup_agent
        self.payment_service = payment_service
        self.waitlist = WaitlistService()

    def book(self, db: Session, request: PublicBookingRequest) -> BookingResult:
        professional = self.schedule_agent.lock_professional(db, request.professional_id)
        patient = self.reception_agent.resolve_patient_for_public_booking(db, request)
        starts_at = ensure_local_naive(request.starts_at, self.settings.app_timezone)

        existing_hold = self._take_over_pending_holds(db, patient, professional, starts_at)
        if existing_hold is not None:
            self.schedule_agent.commit(db)
            return self._with_checkout(db, existing_hold)

        duration = self.schedule_agent.published_slot_duration(db, professional=professional, starts_at=starts_at)
        if duration is None:
            raise DomainError(SLOT_TAKEN_MESSAGE, status_code=409)
        self._enforce_patient_limits(db, patient, professional, starts_at)

        deposit = self.payment_service.deposit_for(professional)
        requires_deposit = deposit > 0
        appointment = self.schedule_agent.insert_appointment(
            db,
            professional=professional,
            patient_id=patient.id,
            starts_at=starts_at,
            duration_minutes=duration,
            status=AppointmentStatus.PENDING_PAYMENT if requires_deposit else AppointmentStatus.RESERVED,
            hold_expires_at=(
                clock.now() + timedelta(minutes=self.settings.booking_hold_minutes) if requires_deposit else None
            ),
            deposit_amount=deposit if requires_deposit else None,
            contact_email=request.email,
            contact_phone=request.phone,
            reason=request.reason or "Reserva online",
            created_by=PUBLIC_ACTOR,
            actor=PUBLIC_ACTOR,
            public_rules=True,
        )
        if not requires_deposit:
            self.followup_agent.queue_confirmation(db, appointment, actor=PUBLIC_ACTOR)
        # Si venía esperando este horario, su anotación se cierra acá.
        self.waitlist.mark_booked_for(db, appointment.patient_id, appointment.starts_at)
        # Commit the hold before talking to the payment provider so the professional lock is not
        # kept during a network call; a provider failure leaves a retryable held slot.
        self.schedule_agent.commit(db)
        appointment = self.schedule_agent.get_appointment(db, appointment.id)
        if not requires_deposit:
            return BookingResult(appointment=appointment)
        return self._with_checkout(db, appointment)

    def retry_checkout(self, db: Session, appointment: Appointment) -> BookingResult:
        return self._with_checkout(db, appointment)

    def can_cancel_online(self, appointment: Appointment) -> bool:
        if appointment.status not in {AppointmentStatus.RESERVED, AppointmentStatus.CONFIRMED}:
            return False
        notice = timedelta(hours=self.settings.cancellation_notice_hours)
        return appointment.starts_at - clock.now() >= notice

    def cancel_by_patient(self, db: Session, appointment: Appointment, *, channel: str) -> Appointment:
        """Self-service cancellation (booking link or WhatsApp), honouring the notice period."""
        if appointment.status not in {AppointmentStatus.RESERVED, AppointmentStatus.CONFIRMED}:
            raise DomainError("Este turno ya no está activo.", status_code=409)
        if not self.can_cancel_online(appointment):
            phone = f" al {self.settings.clinic_phone}" if self.settings.clinic_phone else ""
            raise DomainError(
                f"Faltan menos de {self.settings.cancellation_notice_hours} horas para el turno, así que no se puede "
                f"cancelar online. Comunicate con el consultorio{phone}.",
                status_code=409,
            )
        self.schedule_agent.apply_transition(
            db,
            appointment,
            AppointmentStatus.CANCELLED,
            followup_agent=self.followup_agent,
        )
        note = f"Cancelado por el paciente ({channel})."
        appointment.notes = f"{appointment.notes}\n{note}" if appointment.notes else note
        create_audit_log(
            db,
            action="appointment.cancelled_by_patient",
            entity_name="appointment",
            entity_id=str(appointment.id),
            actor=f"patient:{channel}",
            description="Appointment cancelled by the patient",
        )
        self.schedule_agent.commit(db)
        return appointment

    def _with_checkout(self, db: Session, appointment: Appointment) -> BookingResult:
        try:
            payment = self.payment_service.start_checkout(db, appointment)
            db.commit()
            return BookingResult(appointment=appointment, payment=payment)
        except DomainError as exc:
            db.rollback()
            if exc.status_code not in {502, 503}:
                raise
            return BookingResult(appointment=appointment, payment=appointment.latest_payment, checkout_error=exc.detail)

    def _take_over_pending_holds(
        self,
        db: Session,
        patient: Patient,
        professional: Professional,
        starts_at,
    ) -> Appointment | None:
        """A patient pays one deposit at a time.

        Submitting the same slot again (double click, back button) returns the existing hold;
        choosing a different slot releases the previous one.
        """
        same_slot = None
        for appointment in self.schedule_agent.upcoming_for_patient(db, patient.id):
            if appointment.status != AppointmentStatus.PENDING_PAYMENT:
                continue
            if appointment.professional_id == professional.id and appointment.starts_at == starts_at:
                same_slot = appointment
                continue
            self.schedule_agent.apply_transition(db, appointment, AppointmentStatus.CANCELLED)
            appointment.notes = "Liberado automáticamente: el paciente inició otra reserva."
            create_audit_log(
                db,
                action="appointment.hold_replaced",
                entity_name="appointment",
                entity_id=str(appointment.id),
                actor=PUBLIC_ACTOR,
                description="Pending hold released because the patient started another booking",
            )
        return same_slot

    def _enforce_patient_limits(self, db: Session, patient: Patient, professional: Professional, starts_at) -> None:
        upcoming = self.schedule_agent.upcoming_for_patient(db, patient.id)
        if any(item.professional_id == professional.id and item.starts_at.date() == starts_at.date() for item in upcoming):
            raise DomainError(
                "Ya tenés un turno con este profesional ese día. Si necesitás cambiarlo, comunicate con el consultorio.",
                status_code=409,
            )
        limit = self.settings.booking_max_active_per_patient
        if len(upcoming) >= limit:
            raise DomainError(
                f"Ya tenés {len(upcoming)} turno(s) próximos, el máximo para reservar online. "
                "Cancelá alguno o comunicate con el consultorio.",
                status_code=409,
            )
