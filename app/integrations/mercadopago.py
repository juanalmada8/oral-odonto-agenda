"""Mercado Pago Checkout Pro client (preferences, payments and webhook signatures).

Docs: https://www.mercadopago.com.ar/developers/es/docs/checkout-pro
"""

import hashlib
import hmac
import logging
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import httpx

from app.core.config import Settings
from app.core.enums import PaymentStatus
from app.integrations.payments import CheckoutRequest, CheckoutSession, PaymentGatewayError, PaymentInfo

logger = logging.getLogger(__name__)

API_BASE_URL = "https://api.mercadopago.com"

STATUS_MAP = {
    "approved": PaymentStatus.APPROVED,
    "authorized": PaymentStatus.IN_PROCESS,
    "pending": PaymentStatus.PENDING,
    "in_process": PaymentStatus.IN_PROCESS,
    "in_mediation": PaymentStatus.IN_PROCESS,
    "rejected": PaymentStatus.REJECTED,
    "cancelled": PaymentStatus.CANCELLED,
    "refunded": PaymentStatus.REFUNDED,
    "charged_back": PaymentStatus.REFUNDED,
}


def mercadopago_signature_manifest(*, data_id: str | None, request_id: str | None, ts: str) -> str:
    # Template documented by Mercado Pago; absent values are omitted and alphanumeric ids lowercased.
    manifest = ""
    if data_id:
        manifest += f"id:{data_id.lower() if data_id.isalnum() else data_id};"
    if request_id:
        manifest += f"request-id:{request_id};"
    return manifest + f"ts:{ts};"


def verify_mercadopago_signature(
    *,
    secret: str,
    signature: str | None,
    request_id: str | None,
    data_id: str | None,
) -> bool:
    if not signature:
        return False
    parts = {}
    for chunk in signature.split(","):
        key, _, value = chunk.strip().partition("=")
        parts[key.strip()] = value.strip()
    ts, received = parts.get("ts"), parts.get("v1")
    if not ts or not received:
        return False
    manifest = mercadopago_signature_manifest(data_id=data_id, request_id=request_id, ts=ts)
    expected = hmac.new(secret.encode(), manifest.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, received)


class MercadoPagoGateway:
    name = "mercadopago"

    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        if not settings.mercadopago_access_token:
            raise ValueError("MERCADOPAGO_ACCESS_TOKEN is not configured")
        self.settings = settings
        self._client = client or httpx.Client(base_url=API_BASE_URL, timeout=httpx.Timeout(15.0, connect=5.0))
        self._auth = {"Authorization": f"Bearer {settings.mercadopago_access_token}"}

    def create_checkout(self, request: CheckoutRequest) -> CheckoutSession:
        body = {
            "items": [
                {
                    "id": "sena-turno",
                    "title": request.title[:250],
                    "description": request.description[:250],
                    "category_id": "services",
                    "quantity": 1,
                    "currency_id": request.currency,
                    "unit_price": float(request.amount),
                }
            ],
            "payer": {
                "name": request.payer_first_name,
                "surname": request.payer_last_name,
                "identification": {"type": "DNI", "number": request.payer_dni},
                **({"email": request.payer_email} if request.payer_email else {}),
            },
            "external_reference": request.reference,
            "back_urls": {
                "success": request.return_url,
                "failure": request.return_url,
                "pending": request.return_url,
            },
            # Approved or rejected on the spot: a held slot cannot wait for manual reviews.
            "binary_mode": True,
            "expires": True,
            "expiration_date_from": datetime.now(ZoneInfo(self.settings.app_timezone)).isoformat(timespec="milliseconds"),
            "expiration_date_to": request.expires_at.isoformat(timespec="milliseconds"),
            # Cash vouchers and ATM payments take days to credit, far longer than the slot hold.
            "payment_methods": {
                "excluded_payment_types": [{"id": "ticket"}, {"id": "atm"}],
                "installments": 1,
            },
            "statement_descriptor": self.settings.mercadopago_statement_descriptor[:22],
            "metadata": {"reference": request.reference},
        }
        if request.return_url.startswith("https://"):
            body["auto_return"] = "approved"
        if request.notification_url:
            body["notification_url"] = request.notification_url

        response = self._request(
            "POST",
            "/checkout/preferences",
            json=body,
            headers={"X-Idempotency-Key": request.reference},
        )
        data = response.json()
        return CheckoutSession(preference_id=str(data["id"]), checkout_url=data["init_point"])

    def get_payment(self, provider_payment_id: str) -> PaymentInfo:
        data = self._request("GET", f"/v1/payments/{provider_payment_id}").json()
        paid_at = None
        if data.get("date_approved"):
            paid_at = (
                datetime.fromisoformat(data["date_approved"])
                .astimezone(ZoneInfo(self.settings.app_timezone))
                .replace(tzinfo=None, microsecond=0)
            )
        return PaymentInfo(
            provider_payment_id=str(data["id"]),
            status=STATUS_MAP.get(data.get("status", ""), PaymentStatus.PENDING),
            status_detail=data.get("status_detail"),
            external_reference=data.get("external_reference"),
            amount=Decimal(str(data.get("transaction_amount") or "0")),
            currency=data.get("currency_id") or "",
            paid_at=paid_at,
            raw={key: data.get(key) for key in ("id", "status", "status_detail", "payment_type_id", "payment_method_id", "date_approved", "transaction_amount", "currency_id", "external_reference", "live_mode")},
        )

    def verify_notification(self, *, signature: str | None, request_id: str | None, data_id: str) -> bool:
        secret = self.settings.mercadopago_webhook_secret
        if not secret:
            # Payment data is always fetched from the API with our token, so an unsigned
            # notification cannot forge an approval; the signature only filters noise.
            logger.warning("MERCADOPAGO_WEBHOOK_SECRET not set: accepting unsigned notification")
            return True
        return verify_mercadopago_signature(secret=secret, signature=signature, request_id=request_id, data_id=data_id)

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        headers = {**self._auth, **kwargs.pop("headers", {})}
        try:
            response = self._client.request(method, path, headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            raise PaymentGatewayError(f"Mercado Pago unreachable: {exc}") from exc
        if response.status_code >= 400:
            logger.error("Mercado Pago %s %s -> %s %s", method, path, response.status_code, response.text[:500])
            raise PaymentGatewayError(f"Mercado Pago responded {response.status_code}")
        return response
