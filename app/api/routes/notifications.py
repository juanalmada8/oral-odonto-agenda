from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_followup_agent, require_roles
from app.core.enums import UserRole
from app.db.session import get_db
from app.models.user import User
from app.schemas.notification import ReminderBatchResult, NotificationRead
from app.services.followup_agent import FollowUpAgent

router = APIRouter(
    prefix="/notifications",
    tags=["notifications"],
    dependencies=[Depends(require_roles(UserRole.ADMIN, UserRole.RECEPTIONIST))],
)


@router.get("/", response_model=list[NotificationRead])
def list_notifications(
    db: Session = Depends(get_db),
    followup_agent: FollowUpAgent = Depends(get_followup_agent),
):
    return followup_agent.list_notifications(db)


@router.post("/prepare-reminders", response_model=ReminderBatchResult, status_code=status.HTTP_200_OK)
def prepare_reminders(
    hours_ahead: int = Query(default=24, ge=1, le=168),
    db: Session = Depends(get_db),
    followup_agent: FollowUpAgent = Depends(get_followup_agent),
    current_user: User = Depends(get_current_user),
):
    prepared = followup_agent.prepare_upcoming_reminders(db, hours_ahead=hours_ahead, actor=current_user.username)
    return ReminderBatchResult(prepared=prepared, sent=0, skipped=0)


@router.post("/send-pending", response_model=ReminderBatchResult, status_code=status.HTTP_200_OK)
def send_pending_notifications(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    followup_agent: FollowUpAgent = Depends(get_followup_agent),
    current_user: User = Depends(get_current_user),
):
    result = followup_agent.send_pending_notifications(db, limit=limit, actor=current_user.username)
    return ReminderBatchResult(prepared=0, sent=result["sent"], skipped=result["skipped"])
