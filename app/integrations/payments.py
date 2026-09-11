"""Provider-agnostic types for deposit checkouts."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from app.core.enums import PaymentStatus


class PaymentGatewayError(Exception):
    """The provider could not be reached or rejected our request."""


@dataclass(frozen=True)
class CheckoutRequest:
    reference: str
    title: str
    description: str
    amount: Decimal
    currency: str
    payer_email: str | None
    payer_first_name: str
    payer_last_name: str
    payer_dni: str
    expires_at: datetime  # timezone-aware
    return_url: str
    notification_url: str | None


@dataclass(frozen=True)
class CheckoutSession:
    preference_id: str
    checkout_url: str


@dataclass(frozen=True)
class PaymentInfo:
    """A payment as reported by the provider's API (never taken from a notification body)."""

    provider_payment_id: str
    status: PaymentStatus
    external_reference: str | None
    amount: Decimal
    currency: str
    status_detail: str | None = None
    paid_at: datetime | None = None
    raw: dict = field(default_factory=dict)


class PaymentGateway(Protocol):
    name: str

    def create_checkout(self, request: CheckoutRequest) -> CheckoutSession: ...

    def get_payment(self, provider_payment_id: str) -> PaymentInfo: ...

    def verify_notification(self, *, signature: str | None, request_id: str | None, data_id: str) -> bool: ...
