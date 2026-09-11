"""Operational metrics for the clinic: occupancy, deposit conversion, no-shows and revenue.

Clinic-scale volumes (thousands of rows per quarter) are aggregated in Python after two or three
indexed queries, which keeps the definitions readable and identical on SQLite and PostgreSQL.
"""

import csv
import io
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.enums import APPOINTMENT_STATUS_LABELS, AppointmentStatus, PaymentStatus
from app.models.appointment import Appointment
from app.models.availability_window import AvailabilityWindow
from app.models.payment import Payment
from app.models.professional import Professional

# Appointments that consumed agenda time (pending holds are transient and excluded).
OCCUPYING = {AppointmentStatus.RESERVED, AppointmentStatus.CONFIRMED, AppointmentStatus.COMPLETED, AppointmentStatus.NO_SHOW}
ONLINE_SOURCE = "public_booking"


def _ratio(numerator: float, denominator: float) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


@dataclass
class ProfessionalStats:
    professional_id: int
    name: str
    published_minutes: int = 0
    booked_minutes: int = 0
    appointments: int = 0
    completed: int = 0
    no_show: int = 0
    cancelled: int = 0
    deposits: Decimal = Decimal("0")

    @property
    def occupancy(self) -> float | None:
        return _ratio(self.booked_minutes, self.published_minutes)

    @property
    def no_show_rate(self) -> float | None:
        return _ratio(self.no_show, self.completed + self.no_show)


@dataclass
class ClinicStats:
    date_from: date
    date_to: date
    # Keyed by status value ("no_show") so templates can index it with plain strings.
    by_status: Counter = field(default_factory=Counter)
    online: int = 0
    staff: int = 0
    deposit_bookings: int = 0
    deposit_paid: int = 0
    deposits_collected: Decimal = Decimal("0")
    refunds_pending: int = 0
    attendance_confirmed: int = 0
    published_minutes: int = 0
    booked_minutes: int = 0
    lead_days_total: float = 0.0
    lead_days_count: int = 0
    professionals: list[ProfessionalStats] = field(default_factory=list)
    daily: list[tuple[date, int]] = field(default_factory=list)

    @property
    def total(self) -> int:
        """Real appointments in the period (expired unpaid holds never were one)."""
        return sum(count for status, count in self.by_status.items() if status != AppointmentStatus.EXPIRED.value)

    @property
    def occupancy(self) -> float | None:
        return _ratio(self.booked_minutes, self.published_minutes)

    @property
    def deposit_conversion(self) -> float | None:
        return _ratio(self.deposit_paid, self.deposit_bookings)

    @property
    def no_show_rate(self) -> float | None:
        attended = self.by_status[AppointmentStatus.COMPLETED.value]
        missed = self.by_status[AppointmentStatus.NO_SHOW.value]
        return _ratio(missed, attended + missed)

    @property
    def cancellation_rate(self) -> float | None:
        return _ratio(self.by_status[AppointmentStatus.CANCELLED.value], self.total)

    @property
    def online_share(self) -> float | None:
        return _ratio(self.online, self.online + self.staff)

    @property
    def average_lead_days(self) -> float | None:
        return round(self.lead_days_total / self.lead_days_count, 1) if self.lead_days_count else None

    @property
    def max_daily(self) -> int:
        return max((count for _, count in self.daily), default=0)


class AnalyticsService:
    def clinic_stats(
        self,
        db: Session,
        *,
        date_from: date,
        date_to: date,
        professional_id: int | None = None,
    ) -> ClinicStats:
        stats = ClinicStats(date_from=date_from, date_to=date_to)
        start, end = datetime.combine(date_from, time.min), datetime.combine(date_to + timedelta(days=1), time.min)

        professionals_query = select(Professional).order_by(Professional.last_name, Professional.first_name)
        if professional_id:
            professionals_query = professionals_query.where(Professional.id == professional_id)
        per_professional = {
            professional.id: ProfessionalStats(professional.id, f"{professional.first_name} {professional.last_name}")
            for professional in db.scalars(professionals_query)
        }

        windows_query = (
            select(AvailabilityWindow)
            .where(AvailabilityWindow.availability_date >= date_from)
            .where(AvailabilityWindow.availability_date <= date_to)
        )
        if professional_id:
            windows_query = windows_query.where(AvailabilityWindow.professional_id == professional_id)
        for window in db.scalars(windows_query):
            minutes = int(
                (datetime.combine(date.min, window.end_time) - datetime.combine(date.min, window.start_time)).total_seconds()
                // 60
            )
            stats.published_minutes += minutes
            if window.professional_id in per_professional:
                per_professional[window.professional_id].published_minutes += minutes

        appointments_query = (
            select(Appointment)
            .options(selectinload(Appointment.payments))
            .where(Appointment.starts_at >= start)
            .where(Appointment.starts_at < end)
        )
        if professional_id:
            appointments_query = appointments_query.where(Appointment.professional_id == professional_id)
        daily = defaultdict(int)
        for appointment in db.scalars(appointments_query):
            stats.by_status[appointment.status.value] += 1
            row = per_professional.get(appointment.professional_id)
            if appointment.status == AppointmentStatus.EXPIRED:
                if appointment.deposit_amount:
                    stats.deposit_bookings += 1
                continue
            if appointment.created_by == ONLINE_SOURCE:
                stats.online += 1
            else:
                stats.staff += 1
            if appointment.deposit_amount:
                stats.deposit_bookings += 1
                if any(payment.status == PaymentStatus.APPROVED for payment in appointment.payments):
                    stats.deposit_paid += 1
            if appointment.attendance_confirmed_at:
                stats.attendance_confirmed += 1
            if appointment.created_at:
                stats.lead_days_total += max(0.0, (appointment.starts_at - appointment.created_at).total_seconds() / 86400)
                stats.lead_days_count += 1
            if appointment.status in OCCUPYING:
                stats.booked_minutes += appointment.duration_minutes
                daily[appointment.starts_at.date()] += 1
            if row:
                row.appointments += 1
                if appointment.status in OCCUPYING:
                    row.booked_minutes += appointment.duration_minutes
                row.completed += appointment.status == AppointmentStatus.COMPLETED
                row.no_show += appointment.status == AppointmentStatus.NO_SHOW
                row.cancelled += appointment.status == AppointmentStatus.CANCELLED

        payments_query = (
            select(Payment)
            .join(Appointment, Payment.appointment_id == Appointment.id)
            .options(joinedload(Payment.appointment))
            .where(Payment.status == PaymentStatus.APPROVED)
            .where(Payment.paid_at >= start)
            .where(Payment.paid_at < end)
        )
        if professional_id:
            payments_query = payments_query.where(Appointment.professional_id == professional_id)
        for payment in db.scalars(payments_query):
            stats.deposits_collected += payment.amount
            row = per_professional.get(payment.appointment.professional_id)
            if row:
                row.deposits += payment.amount
            if payment.appointment.status in {AppointmentStatus.EXPIRED, AppointmentStatus.CANCELLED}:
                stats.refunds_pending += 1

        day = date_from
        while day <= date_to:
            stats.daily.append((day, daily.get(day, 0)))
            day += timedelta(days=1)
        stats.professionals = [row for row in per_professional.values() if row.published_minutes or row.appointments]
        return stats

    def export_appointments_csv(
        self,
        db: Session,
        *,
        date_from: date,
        date_to: date,
        professional_id: int | None = None,
    ) -> str:
        """Semicolon-separated with BOM so Excel in Spanish opens it correctly."""
        query = (
            select(Appointment)
            .options(
                joinedload(Appointment.patient),
                joinedload(Appointment.professional),
                selectinload(Appointment.payments),
            )
            .where(Appointment.starts_at >= datetime.combine(date_from, time.min))
            .where(Appointment.starts_at < datetime.combine(date_to + timedelta(days=1), time.min))
            .order_by(Appointment.starts_at)
        )
        if professional_id:
            query = query.where(Appointment.professional_id == professional_id)
        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=";")
        writer.writerow(
            [
                "fecha", "hora", "duracion_min", "profesional", "paciente", "dni", "estado", "origen",
                "sena", "estado_pago", "asistencia_confirmada", "motivo",
            ]
        )
        for appointment in db.scalars(query).unique():
            payment = appointment.latest_payment
            writer.writerow(
                [
                    appointment.starts_at.strftime("%Y-%m-%d"),
                    appointment.starts_at.strftime("%H:%M"),
                    appointment.duration_minutes,
                    f"{appointment.professional.first_name} {appointment.professional.last_name}",
                    f"{appointment.patient.first_name} {appointment.patient.last_name}",
                    appointment.patient.dni,
                    APPOINTMENT_STATUS_LABELS[appointment.status],
                    "online" if appointment.created_by == ONLINE_SOURCE else "consultorio",
                    str(appointment.deposit_amount or "").replace(".", ","),
                    payment.status.value if payment else "",
                    "si" if appointment.attendance_confirmed_at else "",
                    (appointment.reason or "").replace("\n", " "),
                ]
            )
        return "\ufeff" + buffer.getvalue()
