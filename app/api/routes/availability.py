from datetime import date

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_schedule_agent, require_roles
from app.core.enums import UserRole
from app.db.session import get_db
from app.models.user import User
from app.schemas.availability import (
    AvailabilityWindowCreate,
    AvailabilityWindowRead,
    AvailabilityWindowUpdate,
    DailyAvailabilityRead,
    WeeklyAvailabilityDay,
    WeeklyAvailabilityRead,
)
from app.services.schedule_agent import ScheduleAgent

router = APIRouter(
    prefix="/availability",
    tags=["availability"],
    dependencies=[Depends(require_roles(UserRole.ADMIN, UserRole.RECEPTIONIST))],
)


@router.get("/", response_model=DailyAvailabilityRead)
def get_daily_availability(
    professional_id: int,
    agenda_date: date = Query(..., alias="date"),
    db: Session = Depends(get_db),
    schedule_agent: ScheduleAgent = Depends(get_schedule_agent),
):
    slots = schedule_agent.get_daily_availability(db, professional_id=professional_id, day=agenda_date)
    return DailyAvailabilityRead(professional_id=professional_id, date=agenda_date, slots=slots)


@router.get("/week", response_model=WeeklyAvailabilityRead)
def get_weekly_availability(
    professional_id: int,
    week_start: date,
    db: Session = Depends(get_db),
    schedule_agent: ScheduleAgent = Depends(get_schedule_agent),
):
    days = schedule_agent.get_weekly_availability(db, professional_id=professional_id, week_start=week_start)
    return WeeklyAvailabilityRead(
        professional_id=professional_id,
        week_start=week_start,
        days=[WeeklyAvailabilityDay(date=day, slots=slots) for day, slots in days.items()],
    )


@router.get("/windows", response_model=list[AvailabilityWindowRead])
def list_availability_windows(
    professional_id: int | None = None,
    date_from: date | None = None,
    db: Session = Depends(get_db),
    schedule_agent: ScheduleAgent = Depends(get_schedule_agent),
):
    return schedule_agent.list_availability_windows(db, professional_id=professional_id, date_from=date_from)


@router.post("/windows", response_model=AvailabilityWindowRead, status_code=status.HTTP_201_CREATED)
def create_availability_window(
    payload: AvailabilityWindowCreate,
    db: Session = Depends(get_db),
    schedule_agent: ScheduleAgent = Depends(get_schedule_agent),
    current_user: User = Depends(get_current_user),
):
    return schedule_agent.create_availability_window(db, payload, actor=current_user.username)


@router.put("/windows/{availability_window_id}", response_model=AvailabilityWindowRead)
def update_availability_window(
    availability_window_id: int,
    payload: AvailabilityWindowUpdate,
    db: Session = Depends(get_db),
    schedule_agent: ScheduleAgent = Depends(get_schedule_agent),
    current_user: User = Depends(get_current_user),
):
    return schedule_agent.update_availability_window(db, availability_window_id, payload, actor=current_user.username)


@router.delete("/windows/{availability_window_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_availability_window(
    availability_window_id: int,
    db: Session = Depends(get_db),
    schedule_agent: ScheduleAgent = Depends(get_schedule_agent),
    current_user: User = Depends(get_current_user),
):
    schedule_agent.delete_availability_window(db, availability_window_id, actor=current_user.username)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
