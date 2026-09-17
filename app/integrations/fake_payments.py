"""Local stand-in for Mercado Pago, so the whole deposit flow can be exercised without credentials.

Only wired outside production. The checkout URL points to /pagos/simulador/<reference>, where the
developer approves or rejects the payment.
"""

from app.integrations.payments import CheckoutRequest, CheckoutSession, PaymentGatewayError, PaymentInfo


class FakePaymentGateway:
    name = "simulator"

    def create_checkout(self, request: CheckoutRequest) -> CheckoutSession:
        return CheckoutSession(
            preference_id=f"sim-{request.reference}",
            checkout_url=f"/pagos/simulador/{request.reference}",
        )

    def get_payment(self, provider_payment_id: str) -> PaymentInfo:
        raise PaymentGatewayError("The simulator applies payments directly; there is nothing to fetch")

    def verify_notification(self, *, signature: str | None, request_id: str | None, data_id: str) -> bool:
        return False
