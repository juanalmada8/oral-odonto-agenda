"""Schedule agent: manages availability and protects the clinic calendar."""

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.core import clock
from app.core.config import Settings
from app.core.enums import BLOCKING_APPOINTMENT_STATUSES, UPCOMING_APPOINTMENT_STATUSES, AppointmentStatus
from app.core.exceptions import DomainError
from app.models.appointment import Appointment
from app.models.availability_window import AvailabilityWindow
from app.models.professional import Professional
from app.schemas.appointment import AppointmentCreate, AppointmentReschedule, AppointmentUpdate
from app.schemas.availability import (
    AvailabilityBulkResult,
    AvailabilitySlot,
    AvailabilityWindowCreate,
    AvailabilityWindowUpdate,
    RecurringAvailabilityCreate,
)
from app.services.followup_agent import FollowUpAgent
from app.services.reception_agent import ReceptionAgent
from app.services.waitlist_service import WaitlistService
from app.utils.audit import create_audit_log
from app.utils.formatting import format_long_date
from app.utils.datetime import calculate_end, combine_date_time, date_range_end, date_range_start, ensure_local_naive


SLOT_TAKEN_MESSAGE = "Ese horario ya no está disponible. Elegí otro, por favor."

ALLOWED_TRANSITIONS: dict[AppointmentStatus, set[AppointmentStatus]] = {
    AppointmentStatus.PENDING_PAYMENT: {
        AppointmentStatus.CONFIRMED,
        AppointmentStatus.RESERVED,
        AppointmentStatus.CANCELLED,
        AppointmentStatus.EXPIRED,
    },
    AppointmentStatus.RESERVED: {
        AppointmentStatus.CONFIRMED,
        AppointmentStatus.CANCELLED,
        AppointmentStatus.COMPLETED,
        AppointmentStatus.NO_SHOW,
    },
    AppointmentStatus.CONFIRMED: {
        AppointmentStatus.CANCELLED,
        AppointmentStatus.COMPLETED,
        AppointmentStatus.NO_SHOW,
    },
    AppointmentStatus.CANCELLED: {AppointmentStatus.RESERVED},
    AppointmentStatus.EXPIRED: {AppointmentStatus.RESERVED, AppointmentStatus.CONFIRMED},
    AppointmentStatus.COMPLETED: {AppointmentStatus.NO_SHOW},
    AppointmentStatus.NO_SHOW: {AppointmentStatus.COMPLETED},
}

# Moving into these states takes the slot again, so the calendar must be re-validated.
REACTIVATING_SOURCES = {AppointmentStatus.CANCELLED, AppointmentStatus.EXPIRED}


class ScheduleAgent:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.timezone_name = settings.app_timezone
        self.waitlist = WaitlistService()

    # ------------------------------------------------------------------ queries

    def list_appointments(
        self,
        db: Session,
        *,
        professional_id: int | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        status: AppointmentStatus | None = None,
    ) -> list[Appointment]:
        query = (
            select(Appointment)
            .options(joinedload(Appointment.patient), joinedload(Appointment.professional))
            .order_by(Appointment.starts_at)
        )
        if professional_id:
            query = query.where(Appointment.professional_id == professional_id)
        if date_from:
            query = query.where(Appointment.starts_at >= ensure_local_naive(date_from, self.timezone_name))
        if date_to:
            query = query.where(Appointment.starts_at <= ensure_local_naive(date_to, self.timezone_name))
        if status:
            query = query.where(Appointment.status == status)
        return list(db.scalars(query))

    def get_appointment(self, db: Session, appointment_id: int) -> Appointment:
        appointment = db.scalar(
            select(Appointment)
            .options(joinedload(Appointment.patient), joinedload(Appointment.professional))
            .where(Appointment.id == appointment_id)
        )
        if not appointment:
            raise DomainError("No encontramos el turno.", status_code=404)
        return appointment

    def get_appointment_by_token(self, db: Session, public_token: str) -> Appointment:
        appointment = db.scalar(
            select(Appointment)
            .options(joinedload(Appointment.patient), joinedload(Appointment.professional))
            .where(Appointment.public_token == public_token)
        )
        if not appointment:
            raise DomainError("No encontramos el turno.", status_code=404)
        return appointment

    def get_daily_agenda(self, db: Session, *, day: date, professional_id: int | None = None) -> list[Appointment]:
        return self.list_appointments(
            db,
            professional_id=professional_id,
            date_from=date_range_start(day),
            date_to=date_range_end(day),
        )

    def get_weekly_agenda(self, db: Session, *, week_start: date, professional_id: int | None = None) -> list[Appointment]:
        return self.list_appointments(
            db,
            professional_id=professional_id,
            date_from=date_range_start(week_start),
            date_to=date_range_end(week_start + timedelta(days=6)),
        )

    # ------------------------------------------------------------- appointments

    def create_appointment(
        self,
        db: Session,
        payload: AppointmentCreate,
        *,
        reception_agent: ReceptionAgent,
        followup_agent: FollowUpAgent,
        actor: str = "schedule_agent",
    ) -> Appointment:
        """Staff/API booking: no deposit, lands directly as reserved."""
        professional = self.lock_professional(db, payload.professional_id)
        patient = reception_agent.resolve_patient(
            db,
            patient_id=payload.patient_id,
            patient_payload=payload.patient,
            actor=actor,
        )
        starts_at = ensure_local_naive(payload.starts_at, self.timezone_name)
        duration = payload.duration_minutes or professional.default_appointment_duration
        appointment = self.insert_appointment(
            db,
            professional=professional,
            patient_id=patient.id,
            starts_at=starts_at,
            duration_minutes=duration,
            status=AppointmentStatus.RESERVED,
            reason=payload.reason,
            notes=payload.notes,
            created_by=payload.created_by,
            actor=actor,
        )
        followup_agent.queue_confirmation(db, appointment, actor=actor)
        self.commit(db)
        return self.get_appointment(db, appointment.id)

    def insert_appointment(
        self,
        db: Session,
        *,
        professional: Professional,
        patient_id: int,
        starts_at: datetime,
        duration_minutes: int,
        status: AppointmentStatus,
        actor: str,
        created_by: str,
        reason: str | None = None,
        notes: str | None = None,
        contact_email: str | None = None,
        contact_phone: str | None = None,
        hold_expires_at: datetime | None = None,
        deposit_amount: Decimal | None = None,
        public_rules: bool = False,
    ) -> Appointment:
        """Validate and add an appointment to the session. The caller must hold the professional lock."""
        ends_at = calculate_end(starts_at, duration_minutes)
        self.release_expired_holds(db, professional_id=professional.id)
        self.validate_slot(
            db,
            professional=professional,
            starts_at=starts_at,
            ends_at=ends_at,
            patient_id=patient_id,
            public_rules=public_rules,
        )
        appointment = Appointment(
            patient_id=patient_id,
            professional_id=professional.id,
            starts_at=starts_at,
            ends_at=ends_at,
            duration_minutes=duration_minutes,
            status=status,
            reason=reason,
            notes=notes,
            contact_email=contact_email,
            contact_phone=contact_phone,
            hold_expires_at=hold_expires_at,
            deposit_amount=deposit_amount,
            confirmed_at=clock.now() if status == AppointmentStatus.CONFIRMED else None,
            created_by=created_by,
        )
        db.add(appointment)
        self.flush(db)
        create_audit_log(
            db,
            action="appointment.created",
            entity_name="appointment",
            entity_id=str(appointment.id),
            actor=actor,
            description="Appointment created",
            details={
                "patient_id": patient_id,
                "professional_id": professional.id,
                "starts_at": starts_at.isoformat(),
                "status": status.value,
            },
        )
        db.refresh(appointment)
        return appointment

    def update_appointment(
        self,
        db: Session,
        appointment_id: int,
        payload: AppointmentUpdate,
        *,
        followup_agent: FollowUpAgent | None = None,
        actor: str = "schedule_agent",
    ) -> Appointment:
        appointment = self.get_appointment(db, appointment_id)
        changes = payload.model_dump(exclude_unset=True)
        new_status = changes.get("status")
        if new_status == appointment.status:
            new_status = None

        if "starts_at" in changes or "duration_minutes" in changes:
            starts_at = ensure_local_naive(changes.get("starts_at") or appointment.starts_at, self.timezone_name)
            duration = changes.get("duration_minutes") or appointment.duration_minutes
            ends_at = calculate_end(starts_at, duration)
            if (starts_at, ends_at) != (appointment.starts_at, appointment.ends_at):
                professional = self.lock_professional(db, appointment.professional_id)
                self.release_expired_holds(db, professional_id=professional.id)
                self.validate_slot(
                    db,
                    professional=professional,
                    starts_at=starts_at,
                    ends_at=ends_at,
                    patient_id=appointment.patient_id,
                    exclude_appointment_id=appointment.id,
                )
                previous_when = f"{format_long_date(appointment.starts_at)} a las {appointment.starts_at:%H:%M} h"
                appointment.starts_at = starts_at
                appointment.ends_at = ends_at
                appointment.duration_minutes = duration
                if followup_agent:
                    followup_agent.discard_pending_reminders(db, appointment)
                    # Sin este aviso el paciente se presenta en el horario viejo.
                    if appointment.status in UPCOMING_APPOINTMENT_STATUSES:
                        followup_agent.queue_reschedule(db, appointment, previous_when=previous_when, actor=actor)

        for field in ("reason", "notes", "charged_amount"):
            if field in changes:
                setattr(appointment, field, changes[field])

        if new_status:
            self.apply_transition(db, appointment, new_status, followup_agent=followup_agent)

        create_audit_log(
            db,
            action="appointment.updated",
            entity_name="appointment",
            entity_id=str(appointment.id),
            actor=actor,
            description="Appointment updated",
            details=changes,
        )
        self.commit(db)
        return self.get_appointment(db, appointment.id)

    def reschedule_appointment(
        self,
        db: Session,
        appointment_id: int,
        payload: AppointmentReschedule,
        *,
        followup_agent: FollowUpAgent | None = None,
        actor: str = "schedule_agent",
    ) -> Appointment:
        return self.update_appointment(
            db,
            appointment_id,
            AppointmentUpdate(starts_at=payload.starts_at, duration_minutes=payload.duration_minutes),
            followup_agent=followup_agent,
            actor=actor,
        )

    def change_status(
        self,
        db: Session,
        appointment_id: int,
        new_status: AppointmentStatus,
        *,
        followup_agent: FollowUpAgent | None = None,
        notes: str | None = None,
        actor: str = "schedule_agent",
    ) -> Appointment:
        appointment = self.get_appointment(db, appointment_id)
        if appointment.status == new_status:
            raise DomainError("El turno ya está en ese estado.", status_code=409)
        self.apply_transition(db, appointment, new_status, followup_agent=followup_agent)
        if notes:
            appointment.notes = notes
        create_audit_log(
            db,
            action=f"appointment.{new_status.value}",
            entity_name="appointment",
            entity_id=str(appointment.id),
            actor=actor,
            description=f"Appointment moved to {new_status.value}",
        )
        self.commit(db)
        return self.get_appointment(db, appointment.id)

    def confirm_appointment(self, db: Session, appointment_id: int, *, followup_agent: FollowUpAgent | None = None, actor: str = "schedule_agent") -> Appointment:
        return self.change_status(db, appointment_id, AppointmentStatus.CONFIRMED, followup_agent=followup_agent, actor=actor)

    def cancel_appointment(self, db: Session, appointment_id: int, *, notes: str | None = None, followup_agent: FollowUpAgent | None = None, actor: str = "schedule_agent") -> Appointment:
        return self.change_status(db, appointment_id, AppointmentStatus.CANCELLED, followup_agent=followup_agent, notes=notes, actor=actor)

    def complete_appointment(self, db: Session, appointment_id: int, *, notes: str | None = None, actor: str = "schedule_agent") -> Appointment:
        return self.change_status(db, appointment_id, AppointmentStatus.COMPLETED, notes=notes, actor=actor)

    def mark_no_show(self, db: Session, appointment_id: int, *, actor: str = "schedule_agent") -> Appointment:
        return self.change_status(db, appointment_id, AppointmentStatus.NO_SHOW, actor=actor)

    def reserve_appointment(self, db: Session, appointment_id: int, *, actor: str = "schedule_agent") -> Appointment:
        return self.change_status(db, appointment_id, AppointmentStatus.RESERVED, actor=actor)

    def release_expired_holds(
        self,
        db: Session,
        *,
        professional_id: int | None = None,
        followup_agent: FollowUpAgent | None = None,
    ) -> list[Appointment]:
        """Mark unpaid holds whose deadline passed as expired so their slots become bookable."""
        query = (
            select(Appointment)
            .where(Appointment.status == AppointmentStatus.PENDING_PAYMENT)
            .where(Appointment.hold_expires_at.is_not(None))
            .where(Appointment.hold_expires_at <= clock.now())
        )
        if professional_id:
            query = query.where(Appointment.professional_id == professional_id)
        expired = list(db.scalars(query))
        for appointment in expired:
            appointment.status = AppointmentStatus.EXPIRED
            create_audit_log(
                db,
                action="appointment.expired",
                entity_name="appointment",
                entity_id=str(appointment.id),
                actor="schedule_agent",
                description="Unpaid hold expired",
            )
            # El horario vuelve a estar libre: también se ofrece a la lista de espera.
            self.waitlist.notify_freed_slot(db, appointment, followup_agent=followup_agent)
        if expired:
            db.flush()
        return expired

    def apply_transition(
        self,
        db: Session,
        appointment: Appointment,
        new_status: AppointmentStatus,
        *,
        followup_agent: FollowUpAgent | None = None,
    ) -> None:
        current = appointment.status
        if new_status not in ALLOWED_TRANSITIONS.get(current, set()):
            raise DomainError(
                f"No se puede pasar un turno de «{current.value}» a «{new_status.value}».",
                status_code=409,
            )
        if current in REACTIVATING_SOURCES:
            professional = self.lock_professional(db, appointment.professional_id)
            self.release_expired_holds(db, professional_id=professional.id)
            if appointment.starts_at < clock.now():
                raise DomainError("No se puede reactivar un turno que ya pasó.", status_code=409)
            self._assert_slot_free(
                db,
                professional_id=professional.id,
                patient_id=appointment.patient_id,
                starts_at=appointment.starts_at,
                ends_at=appointment.ends_at,
                exclude_appointment_id=appointment.id,
            )

        now = clock.now()
        appointment.status = new_status
        if new_status != AppointmentStatus.PENDING_PAYMENT:
            appointment.hold_expires_at = None
        if new_status == AppointmentStatus.RESERVED:
            appointment.confirmed_at = None
            appointment.cancelled_at = None
        elif new_status == AppointmentStatus.CONFIRMED:
            appointment.confirmed_at = now
            appointment.cancelled_at = None
            if followup_agent:
                followup_agent.queue_confirmation(db, appointment)
        elif new_status == AppointmentStatus.CANCELLED:
            appointment.cancelled_at = now
            if followup_agent:
                followup_agent.discard_pending_reminders(db, appointment)
                # An abandoned unpaid hold was never a real booking for the patient: no email.
                if current in (AppointmentStatus.RESERVED, AppointmentStatus.CONFIRMED):
                    followup_agent.queue_cancellation(db, appointment)
                # El horario quedó libre: se lo ofrecemos a quien esté esperando.
                self.waitlist.notify_freed_slot(db, appointment, followup_agent=followup_agent)
        self.flush(db)

    # ------------------------------------------------------------ availability

    def list_availability_windows(
        self,
        db: Session,
        *,
        professional_id: int | None = None,
        date_from: date | None = None,
    ) -> list[AvailabilityWindow]:
        query = select(AvailabilityWindow).order_by(
            AvailabilityWindow.availability_date,
            AvailabilityWindow.start_time,
            AvailabilityWindow.professional_id,
        )
        if professional_id:
            query = query.where(AvailabilityWindow.professional_id == professional_id)
        if date_from:
            query = query.where(AvailabilityWindow.availability_date >= date_from)
        return list(db.scalars(query))

    def create_availability_window(
        self,
        db: Session,
        payload: AvailabilityWindowCreate,
        *,
        actor: str = "admin",
    ) -> AvailabilityWindow:
        self._get_professional(db, payload.professional_id)
        if payload.availability_date < clock.today():
            raise DomainError("No se puede cargar disponibilidad en una fecha pasada.", status_code=422)
        self._validate_availability_window(
            db,
            professional_id=payload.professional_id,
            availability_date=payload.availability_date,
            start_time=payload.start_time,
            end_time=payload.end_time,
        )
        availability_window = AvailabilityWindow(**payload.model_dump())
        db.add(availability_window)
        db.flush()
        create_audit_log(
            db,
            action="availability_window.created",
            entity_name="availability_window",
            entity_id=str(availability_window.id),
            actor=actor,
            description="Availability window created",
        )
        db.commit()
        db.refresh(availability_window)
        return availability_window

    def update_availability_window(
        self,
        db: Session,
        availability_window_id: int,
        payload: AvailabilityWindowUpdate,
        *,
        actor: str = "admin",
    ) -> AvailabilityWindow:
        availability_window = self.get_availability_window(db, availability_window_id)
        changes = payload.model_dump(exclude_unset=True)
        next_date = changes.get("availability_date", availability_window.availability_date)
        next_start = changes.get("start_time", availability_window.start_time)
        next_end = changes.get("end_time", availability_window.end_time)
        self._validate_availability_window(
            db,
            professional_id=availability_window.professional_id,
            availability_date=next_date,
            start_time=next_start,
            end_time=next_end,
            exclude_window_id=availability_window.id,
        )
        self._assert_window_keeps_appointments(
            db,
            availability_window,
            new_start=combine_date_time(next_date, next_start),
            new_end=combine_date_time(next_date, next_end),
        )
        for field, value in changes.items():
            setattr(availability_window, field, value)
        create_audit_log(
            db,
            action="availability_window.updated",
            entity_name="availability_window",
            entity_id=str(availability_window.id),
            actor=actor,
            description="Availability window updated",
            details={key: str(value) for key, value in changes.items()},
        )
        db.commit()
        db.refresh(availability_window)
        return availability_window

    def create_recurring_windows(
        self,
        db: Session,
        payload: RecurringAvailabilityCreate,
        *,
        actor: str = "admin",
    ) -> AvailabilityBulkResult:
        """Create the same block on every selected weekday; dates that clash or already passed are skipped."""
        self._get_professional(db, payload.professional_id)
        today = clock.today()
        created, skipped = 0, []
        day = payload.date_from
        while day <= payload.date_to:
            if day.weekday() in payload.weekdays:
                clashes = db.scalar(
                    select(AvailabilityWindow.id)
                    .where(AvailabilityWindow.professional_id == payload.professional_id)
                    .where(AvailabilityWindow.availability_date == day)
                    .where(AvailabilityWindow.start_time < payload.end_time)
                    .where(AvailabilityWindow.end_time > payload.start_time)
                    .limit(1)
                )
                if day < today or clashes:
                    skipped.append(day)
                else:
                    db.add(
                        AvailabilityWindow(
                            professional_id=payload.professional_id,
                            availability_date=day,
                            start_time=payload.start_time,
                            end_time=payload.end_time,
                            slot_duration_minutes=payload.slot_duration_minutes,
                            notes=payload.notes,
                        )
                    )
                    created += 1
            day += timedelta(days=1)
        create_audit_log(
            db,
            action="availability_window.bulk_created",
            entity_name="professional",
            entity_id=str(payload.professional_id),
            actor=actor,
            description="Recurring availability created",
            details={"created": created, "skipped": [item.isoformat() for item in skipped]},
        )
        db.commit()
        return AvailabilityBulkResult(created=created, skipped_dates=skipped)

    def clear_windows(
        self,
        db: Session,
        *,
        professional_id: int,
        date_from: date,
        date_to: date,
        actor: str = "admin",
    ) -> AvailabilityBulkResult:
        """Block days (vacations): remove windows in the range, keeping those with active appointments."""
        if date_to < date_from:
            raise DomainError("La fecha final tiene que ser igual o posterior a la inicial.", status_code=422)
        windows = db.scalars(
            select(AvailabilityWindow)
            .where(AvailabilityWindow.professional_id == professional_id)
            .where(AvailabilityWindow.availability_date >= max(date_from, clock.today()))
            .where(AvailabilityWindow.availability_date <= date_to)
        ).all()
        removed, kept = 0, []
        for window in windows:
            try:
                self._assert_window_keeps_appointments(db, window, new_start=None, new_end=None)
            except DomainError:
                kept.append(window.availability_date)
                continue
            db.delete(window)
            removed += 1
        create_audit_log(
            db,
            action="availability_window.bulk_deleted",
            entity_name="professional",
            entity_id=str(professional_id),
            actor=actor,
            description="Availability cleared for a date range",
            details={"removed": removed, "kept": [item.isoformat() for item in kept]},
        )
        db.commit()
        return AvailabilityBulkResult(removed=removed, skipped_dates=sorted(set(kept)))

    def get_availability_window(self, db: Session, availability_window_id: int) -> AvailabilityWindow:
        availability_window = db.get(AvailabilityWindow, availability_window_id)
        if not availability_window:
            raise DomainError("No encontramos esa disponibilidad.", status_code=404)
        return availability_window

    def delete_availability_window(self, db: Session, availability_window_id: int, *, actor: str = "admin") -> None:
        availability_window = self.get_availability_window(db, availability_window_id)
        self._assert_window_keeps_appointments(db, availability_window, new_start=None, new_end=None)
        create_audit_log(
            db,
            action="availability_window.deleted",
            entity_name="availability_window",
            entity_id=str(availability_window.id),
            actor=actor,
            description="Availability window deleted",
        )
        db.delete(availability_window)
        db.commit()

    def public_booking_bounds(self) -> tuple[datetime, date]:
        """Earliest start and last date a patient may book online."""
        now = clock.now()
        earliest = now + timedelta(minutes=self.settings.booking_min_lead_minutes)
        last_date = now.date() + timedelta(days=self.settings.booking_max_days_ahead)
        return earliest, last_date

    def compute_availability(
        self,
        db: Session,
        *,
        professional_id: int,
        date_from: date,
        date_to: date,
        earliest_start: datetime | None = None,
    ) -> dict[date, list[AvailabilitySlot]]:
        """Free slots per day in [date_from, date_to], computed with two queries."""
        professional = self._get_professional(db, professional_id)
        earliest_start = earliest_start or clock.now()
        windows = db.scalars(
            select(AvailabilityWindow)
            .where(AvailabilityWindow.professional_id == professional.id)
            .where(AvailabilityWindow.availability_date >= date_from)
            .where(AvailabilityWindow.availability_date <= date_to)
            .order_by(AvailabilityWindow.availability_date, AvailabilityWindow.start_time)
        ).all()
        if not windows:
            return {}
        busy = db.execute(
            select(Appointment.starts_at, Appointment.ends_at)
            .where(Appointment.professional_id == professional.id)
            .where(Appointment.starts_at < date_range_start(date_to + timedelta(days=1)))
            .where(Appointment.ends_at > date_range_start(date_from))
            .where(self._blocking_filter())
        ).all()

        availability: dict[date, list[AvailabilitySlot]] = defaultdict(list)
        for window in windows:
            for slot_start, slot_end in self._window_slots(window, professional):
                if slot_start < earliest_start:
                    continue
                if any(busy_start < slot_end and busy_end > slot_start for busy_start, busy_end in busy):
                    continue
                availability[window.availability_date].append(
                    AvailabilitySlot(starts_at=slot_start, ends_at=slot_end, available=True)
                )
        return dict(availability)

    def get_daily_availability(
        self,
        db: Session,
        *,
        professional_id: int,
        day: date,
        earliest_start: datetime | None = None,
    ) -> list[AvailabilitySlot]:
        return self.compute_availability(
            db,
            professional_id=professional_id,
            date_from=day,
            date_to=day,
            earliest_start=earliest_start,
        ).get(day, [])

    def list_available_dates(
        self,
        db: Session,
        *,
        professional_id: int,
        date_from: date | None = None,
        date_to: date | None = None,
        earliest_start: datetime | None = None,
        limit: int = 12,
    ) -> list[tuple[date, int]]:
        start_date = date_from or clock.today()
        end_date = date_to or start_date + timedelta(days=self.settings.booking_max_days_ahead)
        availability = self.compute_availability(
            db,
            professional_id=professional_id,
            date_from=start_date,
            date_to=end_date,
            earliest_start=earliest_start,
        )
        return [(day, len(slots)) for day, slots in sorted(availability.items()) if slots][:limit]

    def get_weekly_availability(self, db: Session, *, professional_id: int, week_start: date) -> dict[date, list[AvailabilitySlot]]:
        availability = self.compute_availability(
            db,
            professional_id=professional_id,
            date_from=week_start,
            date_to=week_start + timedelta(days=6),
        )
        return {week_start + timedelta(days=index): availability.get(week_start + timedelta(days=index), []) for index in range(7)}

    def published_slot_duration(self, db: Session, *, professional: Professional, starts_at: datetime) -> int | None:
        """Duration of the published slot starting exactly at `starts_at`, if there is one."""
        windows = db.scalars(
            select(AvailabilityWindow)
            .where(AvailabilityWindow.professional_id == professional.id)
            .where(AvailabilityWindow.availability_date == starts_at.date())
        ).all()
        for window in windows:
            for slot_start, slot_end in self._window_slots(window, professional):
                if slot_start == starts_at:
                    return int((slot_end - slot_start).total_seconds() // 60)
        return None

    def upcoming_for_patient(self, db: Session, patient_id: int) -> list[Appointment]:
        """Appointments the patient is still expected to attend (live holds included)."""
        return list(
            db.scalars(
                select(Appointment)
                .where(Appointment.patient_id == patient_id)
                .where(Appointment.status.in_(UPCOMING_APPOINTMENT_STATUSES))
                .where(self._blocking_filter())
                .where(Appointment.starts_at >= clock.now())
                .order_by(Appointment.starts_at)
            )
        )

    # --------------------------------------------------------------- validation

    def lock_professional(self, db: Session, professional_id: int) -> Professional:
        """Serialize bookings per professional (SELECT ... FOR UPDATE on PostgreSQL)."""
        professional = db.scalar(
            select(Professional).where(Professional.id == professional_id).with_for_update()
        )
        if not professional:
            raise DomainError("No encontramos el profesional.", status_code=404)
        if not professional.is_active:
            raise DomainError("El profesional no está tomando turnos en este momento.", status_code=409)
        return professional

    def validate_slot(
        self,
        db: Session,
        *,
        professional: Professional,
        starts_at: datetime,
        ends_at: datetime,
        patient_id: int | None = None,
        exclude_appointment_id: int | None = None,
        public_rules: bool = False,
    ) -> None:
        if starts_at >= ends_at:
            raise DomainError("El horario de fin debe ser posterior al de inicio.", status_code=422)
        now = clock.now()
        if starts_at < now:
            raise DomainError("No se pueden reservar turnos en horarios que ya pasaron.", status_code=422)
        if public_rules:
            earliest, last_date = self.public_booking_bounds()
            if starts_at < earliest:
                raise DomainError(
                    f"Los turnos online se reservan con al menos {self._format_lead_time()} de anticipación.",
                    status_code=422,
                )
            if starts_at.date() > last_date:
                raise DomainError(
                    f"Solo se pueden reservar turnos online hasta {self.settings.booking_max_days_ahead} días hacia adelante.",
                    status_code=422,
                )
            if not self._is_published_slot(db, professional=professional, starts_at=starts_at, ends_at=ends_at):
                raise DomainError(SLOT_TAKEN_MESSAGE, status_code=409)
        elif not self._fits_availability_windows(db, professional_id=professional.id, starts_at=starts_at, ends_at=ends_at):
            raise DomainError("El horario está fuera de la disponibilidad del profesional para esa fecha.", status_code=409)
        self._assert_slot_free(
            db,
            professional_id=professional.id,
            patient_id=patient_id,
            starts_at=starts_at,
            ends_at=ends_at,
            exclude_appointment_id=exclude_appointment_id,
        )

    def flush(self, db: Session) -> None:
        """Flush, translating the PostgreSQL overlap constraint into a friendly domain error."""
        try:
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            if "no_overlap" in str(exc.orig):
                raise DomainError(SLOT_TAKEN_MESSAGE, status_code=409) from exc
            raise

    def commit(self, db: Session) -> None:
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            if "no_overlap" in str(exc.orig):
                raise DomainError(SLOT_TAKEN_MESSAGE, status_code=409) from exc
            raise

    def _assert_slot_free(
        self,
        db: Session,
        *,
        professional_id: int,
        patient_id: int | None,
        starts_at: datetime,
        ends_at: datetime,
        exclude_appointment_id: int | None = None,
    ) -> None:
        if self._has_overlap(
            db,
            professional_id=professional_id,
            starts_at=starts_at,
            ends_at=ends_at,
            exclude_appointment_id=exclude_appointment_id,
        ):
            raise DomainError(SLOT_TAKEN_MESSAGE, status_code=409)
        if patient_id and self._has_patient_overlap(
            db,
            patient_id=patient_id,
            starts_at=starts_at,
            ends_at=ends_at,
            exclude_appointment_id=exclude_appointment_id,
        ):
            raise DomainError("El paciente ya tiene otro turno en ese horario.", status_code=409)

    def _blocking_filter(self):
        return and_(
            Appointment.status.in_(BLOCKING_APPOINTMENT_STATUSES),
            or_(
                Appointment.status != AppointmentStatus.PENDING_PAYMENT,
                Appointment.hold_expires_at.is_(None),
                Appointment.hold_expires_at > clock.now(),
            ),
        )

    def _window_slots(self, window: AvailabilityWindow, professional: Professional):
        cursor = combine_date_time(window.availability_date, window.start_time)
        window_end = combine_date_time(window.availability_date, window.end_time)
        step = timedelta(minutes=window.slot_duration_minutes or professional.default_appointment_duration)
        while cursor + step <= window_end:
            yield cursor, cursor + step
            cursor += step

    def _is_published_slot(self, db: Session, *, professional: Professional, starts_at: datetime, ends_at: datetime) -> bool:
        windows = db.scalars(
            select(AvailabilityWindow)
            .where(AvailabilityWindow.professional_id == professional.id)
            .where(AvailabilityWindow.availability_date == starts_at.date())
        ).all()
        return any((starts_at, ends_at) in set(self._window_slots(window, professional)) for window in windows)

    def _fits_availability_windows(self, db: Session, *, professional_id: int, starts_at: datetime, ends_at: datetime) -> bool:
        blocks = db.scalars(
            select(AvailabilityWindow)
            .where(AvailabilityWindow.professional_id == professional_id)
            .where(AvailabilityWindow.availability_date == starts_at.date())
        ).all()
        for block in blocks:
            block_start = combine_date_time(starts_at.date(), block.start_time)
            block_end = combine_date_time(starts_at.date(), block.end_time)
            if starts_at >= block_start and ends_at <= block_end:
                return True
        return False

    def _validate_availability_window(
        self,
        db: Session,
        *,
        professional_id: int,
        availability_date: date,
        start_time: time,
        end_time: time,
        exclude_window_id: int | None = None,
    ) -> None:
        if end_time <= start_time:
            raise DomainError("La hora de fin debe ser posterior a la de inicio.", status_code=422)
        query = (
            select(AvailabilityWindow)
            .where(AvailabilityWindow.professional_id == professional_id)
            .where(AvailabilityWindow.availability_date == availability_date)
            .where(AvailabilityWindow.start_time < end_time)
            .where(AvailabilityWindow.end_time > start_time)
        )
        if exclude_window_id:
            query = query.where(AvailabilityWindow.id != exclude_window_id)
        if db.scalar(query):
            raise DomainError(
                "El profesional ya tiene otra disponibilidad que se superpone en esa fecha.",
                status_code=409,
            )

    def _assert_window_keeps_appointments(
        self,
        db: Session,
        window: AvailabilityWindow,
        *,
        new_start: datetime | None,
        new_end: datetime | None,
    ) -> None:
        """Refuse to remove or shrink a window that still has upcoming appointments inside it."""
        window_start = combine_date_time(window.availability_date, window.start_time)
        window_end = combine_date_time(window.availability_date, window.end_time)
        booked = db.scalars(
            select(Appointment)
            .where(Appointment.professional_id == window.professional_id)
            .where(Appointment.starts_at >= window_start)
            .where(Appointment.ends_at <= window_end)
            .where(Appointment.starts_at >= clock.now())
            .where(self._blocking_filter())
        ).all()
        stranded = [
            appointment
            for appointment in booked
            if new_start is None or appointment.starts_at < new_start or appointment.ends_at > new_end
        ]
        if stranded:
            raise DomainError(
                f"Hay {len(stranded)} turno(s) activos dentro de esa disponibilidad. "
                "Cancelalos o reprogramalos antes de modificarla.",
                status_code=409,
            )

    def _has_overlap(
        self,
        db: Session,
        *,
        professional_id: int,
        starts_at: datetime,
        ends_at: datetime,
        exclude_appointment_id: int | None = None,
    ) -> bool:
        query = (
            select(Appointment.id)
            .where(Appointment.professional_id == professional_id)
            .where(self._blocking_filter())
            .where(Appointment.starts_at < ends_at)
            .where(Appointment.ends_at > starts_at)
        )
        if exclude_appointment_id:
            query = query.where(Appointment.id != exclude_appointment_id)
        return db.scalar(query.limit(1)) is not None

    def _has_patient_overlap(
        self,
        db: Session,
        *,
        patient_id: int,
        starts_at: datetime,
        ends_at: datetime,
        exclude_appointment_id: int | None = None,
    ) -> bool:
        query = (
            select(Appointment.id)
            .where(Appointment.patient_id == patient_id)
            .where(self._blocking_filter())
            .where(Appointment.starts_at < ends_at)
            .where(Appointment.ends_at > starts_at)
        )
        if exclude_appointment_id:
            query = query.where(Appointment.id != exclude_appointment_id)
        return db.scalar(query.limit(1)) is not None

    def _get_professional(self, db: Session, professional_id: int) -> Professional:
        professional = db.get(Professional, professional_id)
        if not professional:
            raise DomainError("No encontramos el profesional.", status_code=404)
        if not professional.is_active:
            raise DomainError("El profesional no está tomando turnos en este momento.", status_code=409)
        return professional

    def _format_lead_time(self) -> str:
        minutes = self.settings.booking_min_lead_minutes
        if minutes % 60 == 0:
            hours = minutes // 60
            return f"{hours} hora{'s' if hours != 1 else ''}"
        return f"{minutes} minutos"
