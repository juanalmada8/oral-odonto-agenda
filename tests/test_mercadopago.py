"""Mercado Pago integration against a mocked API: preferences, webhooks and signatures."""

import hashlib
import hmac
import json
from datetime import date, time
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

from app.api.deps import get_payment_gateway
from app.core.config import get_settings
from app.core.enums import AppointmentStatus, PaymentStatus
from app.integrations.mercadopago import API_BASE_URL, MercadoPagoGateway, verify_mercadopago_signature
from app.main import app
from app.models.appointment import Appointment
from app.models.availability_window import AvailabilityWindow
from app.models.professional import Professional

settings = get_settings()
WEBHOOK_SECRET = "whsec-test"


class FakeMercadoPagoAPI:
    """Just enough of the Mercado Pago REST API for the flows we use."""

    def __init__(self) -> None:
        self.preferences: list[dict] = []
        self.payments: dict[str, dict] = {}
        self.down = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            return httpx.Response(500, json={"message": "internal_error"})
        assert request.headers["Authorization"] == "Bearer TEST-access-token"
        if request.method == "POST" and request.url.path == "/checkout/preferences":
            body = json.loads(request.content)
            self.preferences.append(body)
            preference_id = f"pref-{len(self.preferences)}"
            return httpx.Response(201, json={"id": preference_id, "init_point": f"https://mp.test/checkout/{preference_id}"})
        if request.method == "GET" and request.url.path.startswith("/v1/payments/"):
            payment = self.payments.get(request.url.path.rsplit("/", 1)[-1])
            return httpx.Response(200, json=payment) if payment else httpx.Response(404, json={"message": "not_found"})
        return httpx.Response(404)

    def add_payment(self, payment_id: str, *, reference: str, status: str = "approved", amount: float = 10000.0, currency="ARS"):
        self.payments[payment_id] = {
            "id": int(payment_id),
            "status": status,
            "status_detail": "accredited" if status == "approved" else "cc_rejected_other_reason",
            "external_reference": reference,
            "transaction_amount": amount,
            "currency_id": currency,
            "date_approved": "2026-03-27T10:05:00.000-03:00" if status == "approved" else None,
            "payment_type_id": "credit_card",
        }


@pytest.fixture()
def mp_api(monkeypatch):
    monkeypatch.setattr(settings, "mercadopago_access_token", "TEST-access-token")
    monkeypatch.setattr(settings, "mercadopago_webhook_secret", WEBHOOK_SECRET)
    api = FakeMercadoPagoAPI()
    client = httpx.Client(base_url=API_BASE_URL, transport=httpx.MockTransport(api.handler))
    app.dependency_overrides[get_payment_gateway] = lambda: MercadoPagoGateway(settings, client=client)
    yield api
    app.dependency_overrides.pop(get_payment_gateway, None)


@pytest.fixture()
def professional_id(db_session) -> int:
    professional = Professional(first_name="Laura", last_name="Gómez", default_appointment_duration=30, deposit_amount=Decimal("10000"))
    db_session.add(professional)
    db_session.flush()
    db_session.add(
        AvailabilityWindow(
            professional_id=professional.id,
            availability_date=date(2026, 3, 30),
            start_time=time(9, 0),
            end_time=time(12, 0),
            slot_duration_minutes=30,
        )
    )
    db_session.commit()
    return professional.id


def start_booking(client, professional_id):
    return client.post(
        "/reservar",
        data={
            "professional_id": str(professional_id),
            "starts_at": "2026-03-30T09:00:00",
            "dni": "30555111",
            "first_name": "Lucía",
            "last_name": "Fernández",
            "email": "lucia@example.com",
            "phone": "11 5555-5555",
            "accept_terms": "1",
        },
        follow_redirects=False,
    )


def signed_headers(data_id: str, *, request_id: str = "req-1", ts: str = "1774616700", secret: str = WEBHOOK_SECRET) -> dict:
    manifest = f"id:{data_id};request-id:{request_id};ts:{ts};"
    signature = hmac.new(secret.encode(), manifest.encode(), hashlib.sha256).hexdigest()
    return {"x-signature": f"ts={ts},v1={signature}", "x-request-id": request_id}


def appointment(db_session) -> Appointment:
    db_session.expire_all()
    return db_session.scalars(select(Appointment)).one()


def test_checkout_preference_is_built_for_a_time_boxed_deposit(client, mp_api, professional_id):
    response = start_booking(client, professional_id)

    assert response.headers["location"] == "https://mp.test/checkout/pref-1"
    body = mp_api.preferences[0]
    assert body["binary_mode"] is True
    assert body["payment_methods"] == {"excluded_payment_types": [{"id": "ticket"}, {"id": "atm"}], "installments": 1}
    assert body["items"][0]["unit_price"] == 10000.0
    assert body["items"][0]["currency_id"] == "ARS"
    assert body["payer"]["identification"] == {"type": "DNI", "number": "30555111"}
    assert body["expires"] is True
    assert body["expiration_date_to"] == "2026-03-27T10:20:00.000-03:00"
    assert "notification_url" not in body  # local http base URL cannot receive webhooks
    assert "auto_return" not in body


def test_public_https_deployments_get_webhooks_and_auto_return(client, mp_api, professional_id, monkeypatch):
    monkeypatch.setattr(settings, "public_base_url", "https://turnos.oral.com.ar")

    start_booking(client, professional_id)

    body = mp_api.preferences[0]
    assert body["notification_url"] == "https://turnos.oral.com.ar/webhooks/mercadopago?source_news=webhooks"
    assert body["auto_return"] == "approved"
    assert body["back_urls"]["success"].startswith("https://turnos.oral.com.ar/reservar/turno/")


def test_signed_webhook_confirms_the_appointment_once(client, db_session, mp_api, professional_id):
    start_booking(client, professional_id)
    reference = appointment(db_session).latest_payment.reference
    mp_api.add_payment("987654", reference=reference)

    first = client.post("/webhooks/mercadopago?data.id=987654&type=payment", headers=signed_headers("987654"))
    replay = client.post("/webhooks/mercadopago?data.id=987654&type=payment", headers=signed_headers("987654"))

    assert first.status_code == replay.status_code == 200
    booked = appointment(db_session)
    assert booked.status == AppointmentStatus.CONFIRMED
    assert booked.latest_payment.status == PaymentStatus.APPROVED
    assert booked.latest_payment.provider_payment_id == "987654"


def test_webhook_with_bad_signature_is_rejected(client, db_session, mp_api, professional_id):
    start_booking(client, professional_id)
    mp_api.add_payment("987654", reference=appointment(db_session).latest_payment.reference)

    response = client.post(
        "/webhooks/mercadopago?data.id=987654&type=payment",
        headers=signed_headers("987654", secret="attacker"),
    )

    assert response.status_code == 401
    assert appointment(db_session).status == AppointmentStatus.PENDING_PAYMENT


def test_underpaid_approval_does_not_confirm(client, db_session, mp_api, professional_id):
    start_booking(client, professional_id)
    mp_api.add_payment("987654", reference=appointment(db_session).latest_payment.reference, amount=1.0)

    client.post("/webhooks/mercadopago?data.id=987654&type=payment", headers=signed_headers("987654"))

    booked = appointment(db_session)
    assert booked.status == AppointmentStatus.PENDING_PAYMENT
    assert booked.latest_payment.status == PaymentStatus.REJECTED
    assert booked.latest_payment.status_detail == "amount_mismatch"


def test_late_rejection_does_not_undo_an_approval(client, db_session, mp_api, professional_id):
    start_booking(client, professional_id)
    reference = appointment(db_session).latest_payment.reference
    mp_api.add_payment("111", reference=reference, status="rejected")
    mp_api.add_payment("222", reference=reference, status="approved")

    client.post("/webhooks/mercadopago?data.id=222&type=payment", headers=signed_headers("222"))
    client.post("/webhooks/mercadopago?data.id=111&type=payment", headers=signed_headers("111"))

    booked = appointment(db_session)
    assert booked.status == AppointmentStatus.CONFIRMED
    assert booked.latest_payment.status == PaymentStatus.APPROVED


def test_other_topics_and_foreign_payments_are_acknowledged(client, db_session, mp_api, professional_id):
    start_booking(client, professional_id)
    mp_api.add_payment("555", reference="not-ours")

    merchant_order = client.post("/webhooks/mercadopago?topic=merchant_order&id=1")
    foreign = client.post("/webhooks/mercadopago?data.id=555&type=payment", headers=signed_headers("555"))

    assert merchant_order.status_code == 200
    assert foreign.status_code == 200
    assert appointment(db_session).status == AppointmentStatus.PENDING_PAYMENT


def test_provider_outage_asks_mercado_pago_to_retry(client, db_session, mp_api, professional_id):
    start_booking(client, professional_id)
    mp_api.down = True

    response = client.post("/webhooks/mercadopago?data.id=987654&type=payment", headers=signed_headers("987654"))

    assert response.status_code == 502


def test_returning_from_checkout_syncs_the_payment_immediately(client, db_session, mp_api, professional_id):
    start_booking(client, professional_id)
    booked = appointment(db_session)
    mp_api.add_payment("987654", reference=booked.latest_payment.reference)

    response = client.get(
        f"/reservar/turno/{booked.public_token}?payment_id=987654&status=approved&external_reference=forged",
        follow_redirects=False,
    )

    assert response.headers["location"] == f"/reservar/turno/{booked.public_token}"
    assert appointment(db_session).status == AppointmentStatus.CONFIRMED


def test_checkout_creation_failure_keeps_the_hold_and_allows_retry(client, db_session, mp_api, professional_id):
    mp_api.down = True

    response = start_booking(client, professional_id)

    booked = appointment(db_session)
    assert response.headers["location"].startswith(f"/reservar/turno/{booked.public_token}")
    assert booked.status == AppointmentStatus.PENDING_PAYMENT
    mp_api.down = False
    retry = client.post(f"/reservar/turno/{booked.public_token}/pagar", follow_redirects=False)
    assert retry.headers["location"].startswith("https://mp.test/checkout/")


@pytest.mark.parametrize(
    ("data_id", "manifest_id"),
    [("123456", "123456"), ("ABC123", "abc123"), ("a-b_c", "a-b_c")],
)
def test_signature_manifest_follows_mercado_pago_rules(data_id, manifest_id):
    ts = "1700000000"
    manifest = f"id:{manifest_id};request-id:req;ts:{ts};"
    valid = hmac.new(b"secret", manifest.encode(), hashlib.sha256).hexdigest()

    assert verify_mercadopago_signature(secret="secret", signature=f"ts={ts},v1={valid}", request_id="req", data_id=data_id)
    assert not verify_mercadopago_signature(secret="secret", signature=f"ts={ts},v1={'0' * 64}", request_id="req", data_id=data_id)
    assert not verify_mercadopago_signature(secret="secret", signature=None, request_id="req", data_id=data_id)
