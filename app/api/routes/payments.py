from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_payment_service, require_roles
from app.core.enums import UserRole
from app.db.session import get_db
from app.schemas.payment import PaymentRead
from app.services.payment_service import PaymentService

router = APIRouter(
    prefix="/payments",
    tags=["payments"],
    dependencies=[Depends(require_roles(UserRole.ADMIN))],
)


@router.get("/", response_model=list[PaymentRead])
def list_payments(
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
    payment_service: PaymentService = Depends(get_payment_service),
):
    return payment_service.list_payments(db, limit=limit)


@router.get("/requires-refund", response_model=list[PaymentRead])
def list_payments_requiring_refund(
    db: Session = Depends(get_db),
    payment_service: PaymentService = Depends(get_payment_service),
):
    """Approved deposits whose appointment expired or was cancelled."""
    return payment_service.payments_requiring_refund(db)
