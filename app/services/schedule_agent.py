"""Schedule agent: manages availability and protects the clinic calendar."""

from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.enums import AppointmentStatus
from app.core.exceptions import DomainError
from app.models.availability_window import AvailabilityWindow
from app.models.appointment import Appointment
from app.models.professional import Professional
from app.schemas.appointment import AppointmentCreate, AppointmentReschedule, AppointmentUpdate
from app.schemas.availability import AvailabilitySlot, AvailabilityWindowCreate, AvailabilityWindowUpdate
from app.services.followup_agent import FollowUpAgent
from app.services.reception_agent import ReceptionAgent
from app.utils.audit import create_audit_log
from app.utils.datetime import calculate_end, combine_date_time, date_range_end, date_range_start, ensure_local_naive


class ScheduleAgent:
    def __init__(self, *, timezone_name: str) -> None:
        self.timezone_name = timezone_name

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
            raise DomainError("Appointment not found", status_code=404)
        return appointment

    def create_appointment(
        self,
        db: Session,
        payload: AppointmentCreate,
        *,
        reception_agent: ReceptionAgent,
        followup_agent: FollowUpAgent,
        actor: str = "schedule_agent",
    ) -> Appointment:
        professional = self._get_professional(db, payload.professional_id)
        patient = reception_agent.resolve_patient(
            db,
            patient_id=payload.patient_id,
            patient_payload=payload.patient,
            actor=actor,
        )

        starts_at = ensure_local_naive(payload.starts_at, self.timezone_name)
        duration = payload.duration_minutes or professional.default_appointment_duration
        ends_at = calculate_end(starts_at, duration)

        self._validate_slot(
            db,
            professional=professional,
            starts_at=starts_at,
            ends_at=ends_at,
            patient_id=patient.id,
        )

        appointment = Appointment(
            patient_id=patient.id,
            professional_id=professional.id,
            starts_at=starts_at,
            ends_at=ends_at,
            duration_minutes=duration,
            reason=payload.reason,
            notes=payload.notes,
            created_by=payload.created_by,
        )
        db.add(appointment)
        db.flush()
        db.refresh(appointment)
        appointment = self.get_appointment(db, appointment.id)
        followup_agent.queue_confirmation(db, appointment, actor=actor)
        create_audit_log(
            db,
            action="appointment.created",
            entity_name="appointment",
            entity_id=str(appointment.id),
            actor=actor,
            description="Appointment created",
            details={
                "patient_id": appointment.patient_id,
                "professional_id": appointment.professional_id,
                "starts_at": appointment.starts_at.isoformat(),
            },
        )
        db.commit()
        return self.get_appointment(db, appointment.id)

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

        if "starts_at" in changes or "duration_minutes" in changes:
            starts_at = ensure_local_naive(changes.get("starts_at", appointment.starts_at), self.timezone_name)
            duration = changes.get("duration_minutes", appointment.duration_minutes)
            ends_at = calculate_end(starts_at, duration)
            professional = self._get_professional(db, appointment.professional_id)
            self._validate_slot(
                db,
                professional=professional,
                starts_at=starts_at,
                ends_at=ends_at,
                patient_id=appointment.patient_id,
                exclude_appointment_id=appointment.id,
            )
            appointment.starts_at = starts_at
            appointment.ends_at = ends_at
            appointment.duration_minutes = duration

        if "status" in changes:
            appointment.status = changes["status"]
            if appointment.status == AppointmentStatus.CONFIRMED:
                appointment.confirmed_at = datetime.now().replace(microsecond=0)
                if followup_agent:
                    followup_agent.queue_confirmation(db, appointment, actor=actor)
            if appointment.status == AppointmentStatus.CANCELLED:
                appointment.cancelled_at = datetime.now().replace(microsecond=0)

        for field in ("reason", "notes"):
            if field in changes:
                setattr(appointment, field, changes[field])

        create_audit_log(
            db,
            action="appointment.updated",
            entity_name="appointment",
            entity_id=str(appointment.id),
            actor=actor,
            description="Appointment updated",
            details=changes,
        )
        db.commit()
        return self.get_appointment(db, appointment.id)

    def reschedule_appointment(
        self,
        db: Session,
        appointment_id: int,
        payload: AppointmentReschedule,
        *,
        actor: str = "schedule_agent",
    ) -> Appointment:
        return self.update_appointment(
            db,
            appointment_id,
            AppointmentUpdate(starts_at=payload.starts_at, duration_minutes=payload.duration_minutes),
            actor=actor,
        )

    def cancel_appointment(self, db: Session, appointment_id: int, *, notes: str | None = None, actor: str = "schedule_agent") -> Appointment:
        appointment = self.get_appointment(db, appointment_id)
        if appointment.status == AppointmentStatus.CANCELLED:
            raise DomainError("Appointment is already cancelled", status_code=409)
        if appointment.status == AppointmentStatus.COMPLETED:
            raise DomainError("Completed appointments cannot be cancelled from this action", status_code=409)
        self._set_status(appointment, AppointmentStatus.CANCELLED)
        if notes:
            appointment.notes = notes
        create_audit_log(
            db,
            action="appointment.cancelled",
            entity_name="appointment",
            entity_id=str(appointment.id),
            actor=actor,
            description="Appointment cancelled",
        )
        db.commit()
        return self.get_appointment(db, appointment.id)

    def confirm_appointment(
        self,
        db: Session,
        appointment_id: int,
        *,
        followup_agent: FollowUpAgent | None = None,
        actor: str = "schedule_agent",
    ) -> Appointment:
        appointment = self.get_appointment(db, appointment_id)
        if appointment.status == AppointmentStatus.CANCELLED:
            raise DomainError("Cancelled appointments must be reactivated first", status_code=409)
        if appointment.status == AppointmentStatus.COMPLETED:
            raise DomainError("Completed appointments cannot be confirmed", status_code=409)
        if appointment.status == AppointmentStatus.CONFIRMED:
            raise DomainError("Appointment is already confirmed", status_code=409)
        self._set_status(appointment, AppointmentStatus.CONFIRMED)
        if followup_agent:
            followup_agent.queue_confirmation(db, appointment, actor=actor)
        create_audit_log(
            db,
            action="appointment.confirmed",
            entity_name="appointment",
            entity_id=str(appointment.id),
            actor=actor,
            description="Appointment confirmed",
        )
        db.commit()
        return self.get_appointment(db, appointment.id)

    def complete_appointment(self, db: Session, appointment_id: int, *, notes: str | None = None, actor: str = "schedule_agent") -> Appointment:
        appointment = self.get_appointment(db, appointment_id)
        if appointment.status == AppointmentStatus.CANCELLED:
            raise DomainError("Cancelled appointments must be reactivated first", status_code=409)
        if appointment.status == AppointmentStatus.COMPLETED:
            raise DomainError("Appointment is already completed", status_code=409)
        self._set_status(appointment, AppointmentStatus.COMPLETED)
        if notes:
            appointment.notes = notes
        create_audit_log(
            db,
            action="appointment.completed",
            entity_name="appointment",
            entity_id=str(appointment.id),
            actor=actor,
            description="Appointment completed",
        )
        db.commit()
        return self.get_appointment(db, appointment.id)

    def reserve_appointment(self, db: Session, appointment_id: int, *, actor: str = "schedule_agent") -> Appointment:
        appointment = self.get_appointment(db, appointment_id)
        if appointment.status != AppointmentStatus.CANCELLED:
            raise DomainError("Only cancelled appointments can be reactivated", status_code=409)
        self._set_status(appointment, AppointmentStatus.RESERVED)
        create_audit_log(
            db,
            action="appointment.reserved",
            entity_name="appointment",
            entity_id=str(appointment.id),
            actor=actor,
            description="Appointment moved to reserved",
        )
        db.commit()
        return self.get_appointment(db, appointment.id)

    def get_daily_agenda(self, db: Session, *, day: date, professional_id: int | None = None) -> list[Appointment]:
        start = date_range_start(day)
        end = date_range_end(day)
        return self.list_appointments(db, professional_id=professional_id, date_from=start, date_to=end)

    def get_weekly_agenda(self, db: Session, *, week_start: date, professional_id: int | None = None) -> list[Appointment]:
        start = date_range_start(week_start)
        end = date_range_end(week_start + timedelta(days=6))
        return self.list_appointments(db, professional_id=professional_id, date_from=start, date_to=end)

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
        availability_window = db.get(AvailabilityWindow, availability_window_id)
        if not availability_window:
            raise DomainError("Availability window not found", status_code=404)
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
        for field, value in changes.items():
            setattr(availability_window, field, value)
        create_audit_log(
            db,
            action="availability_window.updated",
            entity_name="availability_window",
            entity_id=str(availability_window.id),
            actor=actor,
            description="Availability window updated",
            details=changes,
        )
        db.commit()
        db.refresh(availability_window)
        return availability_window

    def delete_availability_window(self, db: Session, availability_window_id: int, *, actor: str = "admin") -> None:
        availability_window = db.get(AvailabilityWindow, availability_window_id)
        if not availability_window:
            raise DomainError("Availability window not found", status_code=404)
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

    def get_daily_availability(self, db: Session, *, professional_id: int, day: date) -> list[AvailabilitySlot]:
        professional = self._get_professional(db, professional_id)
        day_blocks = list(
            db.scalars(
                select(AvailabilityWindow)
                .where(AvailabilityWindow.professional_id == professional.id)
                .where(AvailabilityWindow.availability_date == day)
                .order_by(AvailabilityWindow.start_time)
            )
        )
        slots: list[AvailabilitySlot] = []
        for block in day_blocks:
            cursor = combine_date_time(day, block.start_time)
            block_end = combine_date_time(day, block.end_time)
            slot_duration = block.slot_duration_minutes or professional.default_appointment_duration
            while cursor + timedelta(minutes=slot_duration) <= block_end:
                slot_end = cursor + timedelta(minutes=slot_duration)
                if not self._has_overlap(db, professional_id=professional.id, starts_at=cursor, ends_at=slot_end):
                    slots.append(AvailabilitySlot(starts_at=cursor, ends_at=slot_end, available=True))
                cursor = slot_end
        return slots

    def list_available_dates(
        self,
        db: Session,
        *,
        professional_id: int,
        date_from: date | None = None,
        limit: int = 12,
    ) -> list[tuple[date, int]]:
        professional = self._get_professional(db, professional_id)
        start_date = date_from or date.today()
        candidate_dates = db.scalars(
            select(AvailabilityWindow.availability_date)
            .where(AvailabilityWindow.professional_id == professional.id)
            .where(AvailabilityWindow.availability_date >= start_date)
            .distinct()
            .order_by(AvailabilityWindow.availability_date)
        ).all()

        available_dates: list[tuple[date, int]] = []
        for candidate in candidate_dates:
            slots = self.get_daily_availability(db, professional_id=professional.id, day=candidate)
            if slots:
                available_dates.append((candidate, len(slots)))
            if len(available_dates) >= limit:
                break
        return available_dates

    def get_weekly_availability(self, db: Session, *, professional_id: int, week_start: date) -> dict[date, list[AvailabilitySlot]]:
        return {
            week_start + timedelta(days=index): self.get_daily_availability(
                db,
                professional_id=professional_id,
                day=week_start + timedelta(days=index),
            )
            for index in range(7)
        }

    def _get_professional(self, db: Session, professional_id: int) -> Professional:
        professional = db.get(Professional, professional_id)
        if not professional:
            raise DomainError("Professional not found", status_code=404)
        if not professional.is_active:
            raise DomainError("Professional is inactive", status_code=409)
        return professional

    def _validate_slot(
        self,
        db: Session,
        *,
        professional: Professional,
        starts_at: datetime,
        ends_at: datetime,
        patient_id: int | None = None,
        exclude_appointment_id: int | None = None,
    ) -> None:
        if starts_at >= ends_at:
            raise DomainError("Appointment end time must be later than start time", status_code=422)
        if not self._fits_availability_windows(db, professional_id=professional.id, starts_at=starts_at, ends_at=ends_at):
            raise DomainError("The selected time is outside the professional availability for that date", status_code=409)
        if self._has_overlap(
            db,
            professional_id=professional.id,
            starts_at=starts_at,
            ends_at=ends_at,
            exclude_appointment_id=exclude_appointment_id,
        ):
            raise DomainError("The selected time overlaps an existing appointment", status_code=409)
        if patient_id and self._has_patient_overlap(
            db,
            patient_id=patient_id,
            starts_at=starts_at,
            ends_at=ends_at,
            exclude_appointment_id=exclude_appointment_id,
        ):
            raise DomainError("The patient already has another appointment in that time range", status_code=409)

    def _fits_availability_windows(self, db: Session, *, professional_id: int, starts_at: datetime, ends_at: datetime) -> bool:
        blocks = list(
            db.scalars(
                select(AvailabilityWindow)
                .where(AvailabilityWindow.professional_id == professional_id)
                .where(AvailabilityWindow.availability_date == starts_at.date())
            )
        )
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
        start_time,
        end_time,
        exclude_window_id: int | None = None,
    ) -> None:
        if end_time <= start_time:
            raise DomainError("Availability end time must be later than start time", status_code=422)
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
            raise DomainError("The professional already has another overlapping availability window on that date", status_code=409)

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
            select(Appointment)
            .where(Appointment.professional_id == professional_id)
            .where(Appointment.status != AppointmentStatus.CANCELLED)
            .where(Appointment.starts_at < ends_at)
            .where(Appointment.ends_at > starts_at)
        )
        if exclude_appointment_id:
            query = query.where(Appointment.id != exclude_appointment_id)
        return db.scalar(query) is not None

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
            select(Appointment)
            .where(Appointment.patient_id == patient_id)
            .where(Appointment.status != AppointmentStatus.CANCELLED)
            .where(Appointment.starts_at < ends_at)
            .where(Appointment.ends_at > starts_at)
        )
        if exclude_appointment_id:
            query = query.where(Appointment.id != exclude_appointment_id)
        return db.scalar(query) is not None

    def _set_status(self, appointment: Appointment, status: AppointmentStatus) -> None:
        now = datetime.now().replace(microsecond=0)
        appointment.status = status
        if status == AppointmentStatus.RESERVED:
            appointment.confirmed_at = None
            appointment.cancelled_at = None
            return
        if status == AppointmentStatus.CONFIRMED:
            appointment.confirmed_at = now
            appointment.cancelled_at = None
            return
        if status == AppointmentStatus.CANCELLED:
            appointment.cancelled_at = now
            return
        if status == AppointmentStatus.COMPLETED:
            appointment.cancelled_at = None
