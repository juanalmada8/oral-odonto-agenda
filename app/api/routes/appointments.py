from datetime import date, datetime

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_followup_agent, get_reception_agent, get_schedule_agent, require_roles
from app.core.enums import AppointmentStatus, UserRole
from app.db.session import get_db
from app.models.user import User
from app.schemas.appointment import (
    AppointmentCreate,
    AppointmentRead,
    AppointmentReschedule,
    AppointmentStatusUpdate,
    AppointmentUpdate,
)
from app.services.followup_agent import FollowUpAgent
from app.services.reception_agent import ReceptionAgent
from app.services.schedule_agent import ScheduleAgent

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
    schedule_agent: ScheduleAgent = Depends(get_schedule_agent),
):
    return schedule_agent.list_appointments(
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
    schedule_agent: ScheduleAgent = Depends(get_schedule_agent),
):
    return schedule_agent.get_daily_agenda(db, day=agenda_date, professional_id=professional_id)


@router.get("/weekly", response_model=list[AppointmentRead])
def weekly_agenda(
    week_start: date,
    professional_id: int | None = None,
    db: Session = Depends(get_db),
    schedule_agent: ScheduleAgent = Depends(get_schedule_agent),
):
    return schedule_agent.get_weekly_agenda(db, week_start=week_start, professional_id=professional_id)


@router.get("/{appointment_id}", response_model=AppointmentRead)
def get_appointment(
    appointment_id: int,
    db: Session = Depends(get_db),
    schedule_agent: ScheduleAgent = Depends(get_schedule_agent),
):
    return schedule_agent.get_appointment(db, appointment_id)


@router.post("/", response_model=AppointmentRead, status_code=status.HTTP_201_CREATED)
def create_appointment(
    payload: AppointmentCreate,
    db: Session = Depends(get_db),
    schedule_agent: ScheduleAgent = Depends(get_schedule_agent),
    reception_agent: ReceptionAgent = Depends(get_reception_agent),
    followup_agent: FollowUpAgent = Depends(get_followup_agent),
    current_user: User = Depends(get_current_user),
):
    return schedule_agent.create_appointment(
        db,
        payload,
        reception_agent=reception_agent,
        followup_agent=followup_agent,
        actor=current_user.username,
    )


@router.put("/{appointment_id}", response_model=AppointmentRead)
def update_appointment(
    appointment_id: int,
    payload: AppointmentUpdate,
    db: Session = Depends(get_db),
    schedule_agent: ScheduleAgent = Depends(get_schedule_agent),
    followup_agent: FollowUpAgent = Depends(get_followup_agent),
    current_user: User = Depends(get_current_user),
):
    return schedule_agent.update_appointment(
        db,
        appointment_id,
        payload,
        followup_agent=followup_agent,
        actor=current_user.username,
    )


@router.post("/{appointment_id}/reschedule", response_model=AppointmentRead)
def reschedule_appointment(
    appointment_id: int,
    payload: AppointmentReschedule,
    db: Session = Depends(get_db),
    schedule_agent: ScheduleAgent = Depends(get_schedule_agent),
    current_user: User = Depends(get_current_user),
):
    return schedule_agent.reschedule_appointment(db, appointment_id, payload, actor=current_user.username)


@router.post("/{appointment_id}/cancel", response_model=AppointmentRead)
def cancel_appointment(
    appointment_id: int,
    payload: AppointmentStatusUpdate,
    db: Session = Depends(get_db),
    schedule_agent: ScheduleAgent = Depends(get_schedule_agent),
    current_user: User = Depends(get_current_user),
):
    return schedule_agent.cancel_appointment(db, appointment_id, notes=payload.notes, actor=current_user.username)


@router.post("/{appointment_id}/confirm", response_model=AppointmentRead)
def confirm_appointment(
    appointment_id: int,
    db: Session = Depends(get_db),
    schedule_agent: ScheduleAgent = Depends(get_schedule_agent),
    followup_agent: FollowUpAgent = Depends(get_followup_agent),
    current_user: User = Depends(get_current_user),
):
    return schedule_agent.confirm_appointment(
        db,
        appointment_id,
        followup_agent=followup_agent,
        actor=current_user.username,
    )


@router.post("/{appointment_id}/complete", response_model=AppointmentRead)
def complete_appointment(
    appointment_id: int,
    payload: AppointmentStatusUpdate,
    db: Session = Depends(get_db),
    schedule_agent: ScheduleAgent = Depends(get_schedule_agent),
    current_user: User = Depends(get_current_user),
):
    return schedule_agent.complete_appointment(db, appointment_id, notes=payload.notes, actor=current_user.username)
