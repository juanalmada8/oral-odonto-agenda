import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import PaymentStatus
from app.db.base import Base
from app.db.types import enum_column
from app.models.mixins import TimestampMixin


def generate_payment_reference() -> str:
    return uuid.uuid4().hex


class Payment(TimestampMixin, Base):
    """A deposit charge for an appointment (one per checkout; retries reuse it)."""

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    appointment_id: Mapped[int] = mapped_column(
        ForeignKey("appointment.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # Sent to the provider as external_reference; the only key trusted when a notification arrives.
    reference: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
        index=True,
        default=generate_payment_reference,
    )
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(
        enum_column(PaymentStatus),
        nullable=False,
        default=PaymentStatus.PENDING,
        server_default=PaymentStatus.PENDING.value,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    preference_id: Mapped[str | None] = mapped_column(String(128), index=True)
    checkout_url: Mapped[str | None] = mapped_column(Text())
    provider_payment_id: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    status_detail: Mapped[str | None] = mapped_column(String(120))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    raw_payload: Mapped[dict | None] = mapped_column(JSON)

    appointment = relationship("Appointment", back_populates="payments")
