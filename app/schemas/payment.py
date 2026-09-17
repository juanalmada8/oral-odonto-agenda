from datetime import datetime
from decimal import Decimal

from app.core.enums import PaymentStatus
from app.schemas.common import TimestampedModel


class PaymentRead(TimestampedModel):
    appointment_id: int
    reference: str
    provider: str
    status: PaymentStatus
    amount: Decimal
    currency: str
    provider_payment_id: str | None
    status_detail: str | None
    expires_at: datetime | None
    paid_at: datetime | None
