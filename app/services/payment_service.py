"""Payment service: deposit checkouts and applying provider results to appointments."""

import dataclasses
import logging
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import Settings
from app.core.enums import AppointmentStatus, PaymentStatus
from app.core.exceptions import DomainError
from app.integrations.payments import CheckoutRequest, PaymentGateway, PaymentGatewayError, PaymentInfo
from app.models.appointment import Appointment
from app.models.payment import Payment
from app.models.professional import Professional
from app.services.followup_agent import FollowUpAgent
from app.services.schedule_agent import ScheduleAgent
from app.utils.audit import create_audit_log

logger = logging.getLogger(__name__)

PAYMENTS_UNAVAILABLE = "Los pagos online no están disponibles en este momento. Intentá más tarde o comunicate con el consultorio."

# Once approved, a payment only moves on to refunded; late "rejected"/"pending" notifications
# from earlier attempts on the same checkout must not undo it.
FINAL_AFTER_APPROVAL = {PaymentStatus.APPROVED, PaymentStatus.REFUNDED}


class PaymentService:
    def __init__(
        self,
        settings: Settings,
        gateway: PaymentGateway | None,
        schedule_agent: ScheduleAgent,
        followup_agent: FollowUpAgent,
    ) -> None:
        self.settings = settings
        self.gateway = gateway
        self.schedule_agent = schedule_agent
        self.followup_agent = followup_agent

    def deposit_for(self, professional: Professional) -> Decimal:
        amount = professional.deposit_amount
        if amount is None:
            amount = self.settings.deposit_default_amount
        return Decimal(amount).quantize(Decimal("0.01"))

    def list_payments(self, db: Session, *, limit: int = 200) -> list[Payment]:
        return list(db.scalars(select(Payment).order_by(Payment.id.desc()).limit(limit)))

    def get_by_reference(self, db: Session, reference: str, *, for_update: bool = False) -> Payment:
        query = select(Payment).where(Payment.reference == reference)
        if for_update:
            query = query.with_for_update()
        payment = db.scalar(query)
        if not payment:
            raise DomainError("No encontramos ese pago.", status_code=404)
        return payment

    def start_checkout(self, db: Session, appointment: Appointment) -> Payment:
        """Create (or reuse) the provider checkout for an appointment waiting for its deposit."""
        if appointment.status != AppointmentStatus.PENDING_PAYMENT or not appointment.hold_expires_at:
            raise DomainError("Este turno no tiene una seña pendiente.", status_code=409)
        if appointment.hold_expires_at <= clock.now():
            raise DomainError("El tiempo para pagar la seña venció y el horario se liberó.", status_code=409)
        if self.gateway is None:
            logger.error("Deposit required but no payment gateway is configured")
            raise DomainError(PAYMENTS_UNAVAILABLE, status_code=503)

        payment = appointment.latest_payment
        if payment and payment.checkout_url and payment.status in {PaymentStatus.PENDING, PaymentStatus.REJECTED}:
            return payment
        if payment is None or payment.status not in {PaymentStatus.PENDING, PaymentStatus.REJECTED}:
            payment = Payment(
                appointment_id=appointment.id,
                provider=self.gateway.name,
                amount=appointment.deposit_amount,
                currency=self.settings.currency,
                expires_at=appointment.hold_expires_at,
            )
            db.add(payment)
            db.flush()

        patient = appointment.patient
        professional = appointment.professional
        professional_name = f"{professional.first_name} {professional.last_name}"
        base_url = self.settings.public_base_url
        try:
            session = self.gateway.create_checkout(
                CheckoutRequest(
                    reference=payment.reference,
                    title=f"Seña turno odontológico · {professional_name}",
                    description=f"Turno del {appointment.starts_at:%d/%m/%Y %H:%M} en {self.settings.clinic_name}",
                    amount=payment.amount,
                    currency=payment.currency,
                    payer_email=appointment.notification_email,
                    payer_first_name=patient.first_name,
                    payer_last_name=patient.last_name,
                    payer_dni=patient.dni,
                    expires_at=clock.to_aware(appointment.hold_expires_at),
                    return_url=f"{base_url}/reservar/turno/{appointment.public_token}",
                    # Mercado Pago only calls back public HTTPS endpoints.
                    notification_url=(
                        f"{base_url}/webhooks/mercadopago?source_news=webhooks" if base_url.startswith("https://") else None
                    ),
                )
            )
        except PaymentGatewayError as exc:
            logger.error("Could not create checkout for appointment %s: %s", appointment.id, exc)
            raise DomainError(
                "No pudimos generar el link de pago. Tu horario sigue reservado: intentá de nuevo en unos segundos.",
                status_code=502,
            ) from exc
        payment.preference_id = session.preference_id
        payment.checkout_url = session.checkout_url
        create_audit_log(
            db,
            action="payment.checkout_created",
            entity_name="payment",
            entity_id=str(payment.id),
            actor="payment_service",
            description="Deposit checkout created",
            details={"appointment_id": appointment.id, "amount": str(payment.amount), "provider": payment.provider},
        )
        db.flush()
        return payment

    def sync_provider_payment(self, db: Session, provider_payment_id: str) -> Payment | None:
        """Fetch a payment from the provider and apply it. Returns None for payments that are not ours."""
        if self.gateway is None:
            raise DomainError(PAYMENTS_UNAVAILABLE, status_code=503)
        info = self.gateway.get_payment(provider_payment_id)
        if not info.external_reference:
            return None
        try:
            return self.apply_payment_info(db, info)
        except DomainError as exc:
            if exc.status_code == 404:
                logger.warning("Ignoring provider payment %s with unknown reference", provider_payment_id)
                return None
            raise

    def apply_payment_info(self, db: Session, info: PaymentInfo) -> Payment:
        """Idempotently record a provider result and move the appointment accordingly."""
        payment = self.get_by_reference(db, info.external_reference or "", for_update=True)
        previous_status = payment.status
        next_status = info.status

        if next_status == PaymentStatus.APPROVED and (info.currency != payment.currency or info.amount < payment.amount):
            logger.error(
                "Payment %s approved with %s %s but %s %s was expected",
                payment.reference, info.amount, info.currency, payment.amount, payment.currency,
            )
            next_status = PaymentStatus.REJECTED
            info = dataclasses.replace(info, status=next_status, status_detail="amount_mismatch")

        if previous_status in FINAL_AFTER_APPROVAL and next_status not in FINAL_AFTER_APPROVAL:
            return payment
        if previous_status == next_status and payment.provider_payment_id == info.provider_payment_id:
            return payment

        payment.status = next_status
        payment.provider_payment_id = info.provider_payment_id
        payment.status_detail = info.status_detail
        payment.raw_payload = info.raw or None
        if next_status == PaymentStatus.APPROVED:
            payment.paid_at = info.paid_at or clock.now()
        create_audit_log(
            db,
            action=f"payment.{next_status.value}",
            entity_name="payment",
            entity_id=str(payment.id),
            actor="payment_service",
            description=f"Payment moved from {previous_status.value} to {next_status.value}",
            details={"provider_payment_id": info.provider_payment_id, "status_detail": info.status_detail},
        )
        if next_status == PaymentStatus.APPROVED and previous_status != PaymentStatus.APPROVED:
            self._confirm_paid_appointment(db, payment)
        self.schedule_agent.commit(db)
        return payment

    def expire_unpaid(self, db: Session) -> int:
        """Release holds whose payment window closed and close their pending payments."""
        expired = self.schedule_agent.release_expired_holds(db, followup_agent=self.followup_agent)
        for appointment in expired:
            for payment in appointment.payments:
                if payment.status in {PaymentStatus.PENDING, PaymentStatus.IN_PROCESS, PaymentStatus.REJECTED}:
                    payment.status = PaymentStatus.EXPIRED
        db.commit()
        return len(expired)

    def requires_refund(self, payment: Payment) -> bool:
        """An approved deposit whose appointment is no longer going to happen."""
        return payment.status == PaymentStatus.APPROVED and payment.appointment.status in {
            AppointmentStatus.EXPIRED,
            AppointmentStatus.CANCELLED,
        }

    def payments_requiring_refund(self, db: Session) -> list[Payment]:
        candidates = db.scalars(
            select(Payment)
            .join(Appointment, Payment.appointment_id == Appointment.id)
            .where(Payment.status == PaymentStatus.APPROVED)
            .where(Appointment.status.in_([AppointmentStatus.EXPIRED, AppointmentStatus.CANCELLED]))
            .order_by(Payment.paid_at.desc())
        )
        return list(candidates)

    def register_cash_deposit(self, db: Session, appointment: Appointment, amount: Decimal, *, actor: str) -> Payment:
        """Record a deposit collected at the desk, so the appointment counts as paid like an online one."""
        if amount <= 0:
            raise DomainError("La seña en efectivo tiene que ser mayor a cero.")
        payment = Payment(
            appointment_id=appointment.id,
            provider="efectivo",
            status=PaymentStatus.APPROVED,
            amount=amount,
            currency=self.settings.currency,
            status_detail="cobrada_en_mostrador",
            paid_at=clock.now(),
        )
        db.add(payment)
        db.flush()
        appointment.deposit_amount = amount
        create_audit_log(
            db,
            action="payment.cash_deposit",
            entity_name="appointment",
            entity_id=str(appointment.id),
            actor=actor,
            description="Seña cobrada en efectivo en el consultorio",
            details={"amount": str(amount)},
        )
        # Cobrada la seña, el turno vale lo mismo que uno pagado online.
        self._confirm_paid_appointment(db, payment)
        return payment

    def mark_refunded(self, db: Session, payment_id: int, *, actor: str) -> Payment:
        """Record a refund made outside the provider (transfer, cash at the desk).

        Mercado Pago notifies its own refunds by webhook; this is for the money that goes
        back some other way, so the deposit stops showing up as pending.
        """
        payment = db.get(Payment, payment_id)
        if payment is None:
            raise DomainError("No encontramos ese pago.")
        if payment.status == PaymentStatus.REFUNDED:
            return payment
        if not self.requires_refund(payment):
            # Guards against wiping the deposit of an appointment that is still going to happen.
            raise DomainError("Solo se puede devolver la seña de un turno cancelado o vencido.")

        payment.status = PaymentStatus.REFUNDED
        payment.status_detail = "refunded_manually"
        create_audit_log(
            db,
            action="payment.refunded_manually",
            entity_name="payment",
            entity_id=str(payment.id),
            actor=actor,
            description="Seña marcada como devuelta a mano desde el panel",
            details={"amount": str(payment.amount), "appointment_id": payment.appointment_id},
        )
        self.schedule_agent.commit(db)
        return payment

    def _confirm_paid_appointment(self, db: Session, payment: Payment) -> None:
        appointment = self.schedule_agent.get_appointment(db, payment.appointment_id)
        if appointment.status == AppointmentStatus.CONFIRMED:
            return
        if appointment.status in {AppointmentStatus.COMPLETED, AppointmentStatus.NO_SHOW}:
            return
        try:
            self.schedule_agent.apply_transition(
                db,
                appointment,
                AppointmentStatus.CONFIRMED,
                followup_agent=self.followup_agent,
            )
        except DomainError as exc:
            # Paid after the hold lapsed and someone else took the slot (or it was cancelled):
            # keep the money on record and surface it to the staff for a refund or a new date.
            logger.warning("Payment %s approved but appointment %s cannot be confirmed: %s", payment.id, appointment.id, exc.detail)
            create_audit_log(
                db,
                action="payment.requires_refund",
                entity_name="payment",
                entity_id=str(payment.id),
                actor="payment_service",
                description="Deposit approved for an appointment that could not be confirmed",
                details={"appointment_id": appointment.id, "reason": exc.detail},
            )
            return
        create_audit_log(
            db,
            action="appointment.confirmed_by_payment",
            entity_name="appointment",
            entity_id=str(appointment.id),
            actor="payment_service",
            description="Deposit approved; appointment confirmed",
        )


def hold_seconds_left(appointment: Appointment, now: datetime | None = None) -> int:
    if appointment.status != AppointmentStatus.PENDING_PAYMENT or not appointment.hold_expires_at:
        return 0
    return max(0, int((appointment.hold_expires_at - (now or clock.now())).total_seconds()))
