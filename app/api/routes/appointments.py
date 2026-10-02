from datetime import date, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_followup_service, get_reception_service, get_schedule_service, require_roles
from app.core.enums import AppointmentStatus, UserRole
from app.db.session import get_db
from app.models.user import User
from app.schemas.appointment import (
    AppointmentCreate,
    AppointmentSeriesCreate,
    AppointmentRead,
    AppointmentReschedule,
    AppointmentStatusUpdate,
    AppointmentUpdate,
)
from app.services.followup_service import FollowUpService
from app.services.reception_service import ReceptionService
from app.services.schedule_service import ScheduleService
from app.tasks.notifications import dispatch_due_notifications

router = APIRouter(
    prefix="/appointments",
    tags=["appointments"],
    dependencies=[Depends(require_roles(UserRole.ADMIN, UserRole.RECEPTIONIST))],
)


@router.get("/", response_model=list[AppointmentRead])
def list_appointments(
    professional_id: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    status_filter: AppointmentStatus | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    schedule_service: ScheduleService = Depends(get_schedule_service),
):
    return schedule_service.list_appointments(
        db,
        professional_id=professional_id,
        date_from=date_from,
        date_to=date_to,
        status=status_filter,
    )


@router.get("/daily", response_model=list[AppointmentRead])
def daily_agenda(
    agenda_date: date = Query(..., alias="date"),
    professional_id: int | None = None,
    db: Session = Depends(get_db),
    schedule_service: ScheduleService = Depends(get_schedule_service),
):
    return schedule_service.get_daily_agenda(db, day=agenda_date, professional_id=professional_id)


@router.get("/weekly", response_model=list[AppointmentRead])
def weekly_agenda(
    week_start: date,
    professional_id: int | None = None,
    db: Session = Depends(get_db),
    schedule_service: ScheduleService = Depends(get_schedule_service),
):
    return schedule_service.get_weekly_agenda(db, week_start=week_start, professional_id=professional_id)


@router.get("/{appointment_id}", response_model=AppointmentRead)
def get_appointment(
    appointment_id: int,
    db: Session = Depends(get_db),
    schedule_service: ScheduleService = Depends(get_schedule_service),
):
    return schedule_service.get_appointment(db, appointment_id)


@router.post("/", response_model=AppointmentRead, status_code=status.HTTP_201_CREATED)
def create_appointment(
    payload: AppointmentCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    schedule_service: ScheduleService = Depends(get_schedule_service),
    reception_service: ReceptionService = Depends(get_reception_service),
    followup_service: FollowUpService = Depends(get_followup_service),
    current_user: User = Depends(get_current_user),
):
    appointment = schedule_service.create_appointment(
        db,
        payload,
        reception_service=reception_service,
        followup_service=followup_service,
        actor=current_user.username,
    )
    background_tasks.add_task(dispatch_due_notifications, followup_service)
    return appointment


@router.post("/series", response_model=list[AppointmentRead], status_code=status.HTTP_201_CREATED)
def create_appointment_series(
    payload: AppointmentSeriesCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    schedule_service: ScheduleService = Depends(get_schedule_service),
    reception_service: ReceptionService = Depends(get_reception_service),
    followup_service: FollowUpService = Depends(get_followup_service),
    current_user: User = Depends(get_current_user),
):
    """Los turnos de un tratamiento que repite. Las fechas sin lugar se saltean."""
    result = schedule_service.create_series(
        db,
        payload,
        reception_service=reception_service,
        followup_service=followup_service,
        actor=current_user.username,
    )
    background_tasks.add_task(dispatch_due_notifications, followup_service)
    return result.created
@router.put("/{appointment_id}", response_model=AppointmentRead)
def update_appointment(
    appointment_id: int,
    payload: AppointmentUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    schedule_service: ScheduleService = Depends(get_schedule_service),
    followup_service: FollowUpService = Depends(get_followup_service),
    current_user: User = Depends(get_current_user),
):
    appointment = schedule_service.update_appointment(
        db,
        appointment_id,
        payload,
        followup_service=followup_service,
        actor=current_user.username,
    )
    background_tasks.add_task(dispatch_due_notifications, followup_service)
    return appointment


@router.post("/{appointment_id}/reschedule", response_model=AppointmentRead)
def reschedule_appointment(
    appointment_id: int,
    payload: AppointmentReschedule,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    schedule_service: ScheduleService = Depends(get_schedule_service),
    followup_service: FollowUpService = Depends(get_followup_service),
    current_user: User = Depends(get_current_user),
):
    appointment = schedule_service.reschedule_appointment(
        db,
        appointment_id,
        payload,
        followup_service=followup_service,
        actor=current_user.username,
    )
    background_tasks.add_task(dispatch_due_notifications, followup_service)
    return appointment


@router.post("/{appointment_id}/cancel", response_model=AppointmentRead)
def cancel_appointment(
    appointment_id: int,
    payload: AppointmentStatusUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    schedule_service: ScheduleService = Depends(get_schedule_service),
    followup_service: FollowUpService = Depends(get_followup_service),
    current_user: User = Depends(get_current_user),
):
    appointment = schedule_service.cancel_appointment(
        db,
        appointment_id,
        notes=payload.notes,
        followup_service=followup_service,
        actor=current_user.username,
    )
    background_tasks.add_task(dispatch_due_notifications, followup_service)
    return appointment


@router.post("/{appointment_id}/confirm", response_model=AppointmentRead)
def confirm_appointment(
    appointment_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    schedule_service: ScheduleService = Depends(get_schedule_service),
    followup_service: FollowUpService = Depends(get_followup_service),
    current_user: User = Depends(get_current_user),
):
    appointment = schedule_service.confirm_appointment(
        db,
        appointment_id,
        followup_service=followup_service,
        actor=current_user.username,
    )
    background_tasks.add_task(dispatch_due_notifications, followup_service)
    return appointment


@router.post("/{appointment_id}/complete", response_model=AppointmentRead)
def complete_appointment(
    appointment_id: int,
    payload: AppointmentStatusUpdate,
    db: Session = Depends(get_db),
    schedule_service: ScheduleService = Depends(get_schedule_service),
    current_user: User = Depends(get_current_user),
):
    return schedule_service.complete_appointment(db, appointment_id, notes=payload.notes, actor=current_user.username)
