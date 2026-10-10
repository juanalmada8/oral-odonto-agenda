"""Notification outbox, email content, WhatsApp reminders/bot and the scheduled job."""

import hashlib
import hmac
import json
from datetime import date, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

from app.api.deps import get_email_client, get_whatsapp_client
from app.core.config import get_settings
from app.core.enums import (
    AppointmentStatus,
    NotificationChannel,
    NotificationStatus,
    NotificationType,
    WaitlistPeriod,
    WaitlistStatus,
)
from app.integrations.whatsapp import GRAPH_BASE_URL, WhatsAppClient, same_whatsapp_number
from app.main import app
from app.models.appointment import Appointment
from app.models.patient import Patient
from app.models.notification import Notification
from app.models.waitlist_entry import WaitlistEntry
from app.services.followup_service import FollowUpService
from app.tasks import run_scheduled

settings = get_settings()
APP_SECRET = "meta-app-secret"


class RecordingEmailClient:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.configured = True
        self.failures_left = 0

    def is_configured(self) -> bool:
        return self.configured

    def send_email(self, *, recipient: str, subject: str, body: str, html: str | None = None) -> str:
        if self.failures_left:
            self.failures_left -= 1
            raise OSError("SMTP connection refused")
        self.sent.append({"to": recipient, "subject": subject, "text": body, "html": html})
        return f"<{len(self.sent)}@test>"


class FakeWhatsAppAPI:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v21.0/PHONE_ID/messages"
        body = json.loads(request.content)
        self.messages.append(body)
        return httpx.Response(200, json={"messages": [{"id": f"wamid.OUT{len(self.messages)}"}]})

    def texts(self) -> list[str]:
        return [m["text"]["body"] for m in self.messages if m["type"] == "text"]


@pytest.fixture()
def outbox():
    email_client = RecordingEmailClient()
    app.dependency_overrides[get_email_client] = lambda: email_client
    yield email_client
    app.dependency_overrides.pop(get_email_client, None)


@pytest.fixture()
def whatsapp(monkeypatch):
    monkeypatch.setattr(settings, "whatsapp_access_token", "EAAG-test")
    monkeypatch.setattr(settings, "whatsapp_phone_number_id", "PHONE_ID")
    monkeypatch.setattr(settings, "whatsapp_app_secret", APP_SECRET)
    monkeypatch.setattr(settings, "whatsapp_verify_token", "verify-me")
    api = FakeWhatsAppAPI()
    client = WhatsAppClient(settings, client=httpx.Client(base_url=GRAPH_BASE_URL, transport=httpx.MockTransport(api.handler)))
    app.dependency_overrides[get_whatsapp_client] = lambda: client
    yield api
    app.dependency_overrides.pop(get_whatsapp_client, None)


def followup(email_client, whatsapp_api: FakeWhatsAppAPI | None = None) -> FollowUpService:
    whatsapp_client = None
    if whatsapp_api:
        whatsapp_client = WhatsAppClient(
            settings, client=httpx.Client(base_url=GRAPH_BASE_URL, transport=httpx.MockTransport(whatsapp_api.handler))
        )
    return FollowUpService(settings, email_client, whatsapp_client)


def book(client, professional_id, starts_at="2026-03-30T09:00:00", **overrides):
    data = {
        "professional_id": str(professional_id),
        "starts_at": starts_at,
        "dni": "30555111",
        "first_name": "Lucía",
        "last_name": "O'Connor",
        "email": "lucia@example.com",
        "phone": "11 5555-5555",
        "accept_terms": "1",
        **overrides,
    }
    return client.post("/reservar", data=data, follow_redirects=False)


def confirmed_booking(client, db_session, make_professional) -> Appointment:
    professional_id = make_professional()
    checkout = book(client, professional_id).headers["location"]
    client.post(checkout, data={"decision": "approve"})
    db_session.expire_all()
    return db_session.scalars(select(Appointment)).one()


def webhook(client, payload: dict, secret: str = APP_SECRET):
    raw = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return client.post("/webhooks/whatsapp", content=raw, headers={"X-Hub-Signature-256": signature, "Content-Type": "application/json"})


def button_message(appointment: Appointment, action: str, *, message_id: str = "wamid.IN1", sender: str = "5491155555555", kind="button"):
    message = {"from": sender, "id": message_id, "timestamp": "1774616700", "type": kind}
    payload = f"{action}:{appointment.public_token}"
    if kind == "button":
        message["button"] = {"payload": payload, "text": action}
    else:
        message["interactive"] = {"type": "button_reply", "button_reply": {"id": payload, "title": action}}
    return {"object": "whatsapp_business_account", "entry": [{"changes": [{"field": "messages", "value": {"messages": [message]}}]}]}


# --------------------------------------------------------------------------- emails


def test_paid_booking_sends_a_branded_confirmation_email(client, db_session, make_professional, outbox):
    appointment = confirmed_booking(client, db_session, make_professional)

    assert len(outbox.sent) == 1
    email = outbox.sent[0]
    assert email["to"] == "lucia@example.com"
    assert email["subject"] == "Turno confirmado: 30/03 09:00 h"
    assert "Lunes 30 de marzo" in email["text"]
    assert "$ 10.000" in email["text"]
    assert f"/reservar/turno/{appointment.public_token}" in email["html"]
    assert "Laura Gómez" in email["html"]
    notification = db_session.scalars(select(Notification)).one()
    assert notification.status == NotificationStatus.SENT
    assert notification.provider_message_id == "<1@test>"


def test_only_the_html_email_is_escaped(client, db_session, make_professional, outbox):
    professional_id = make_professional(deposit=Decimal("0"))

    book(client, professional_id, first_name="O'Neil")

    email = outbox.sent[0]
    assert email["subject"] == "Turno reservado: 30/03 09:00 h"
    assert "¡Te esperamos, O'Neil!" in email["text"]
    assert "O&#39;Neil" in email["html"]


def test_failed_email_is_retried_with_backoff_then_marked_failed(client, db_session, make_professional, outbox, frozen_clock):
    outbox.failures_left = 99
    confirmed_booking(client, db_session, make_professional)
    notification = db_session.scalars(select(Notification)).one()
    assert notification.status == NotificationStatus.PENDING
    assert notification.attempts == 1
    assert notification.scheduled_for == frozen_clock.now() + timedelta(minutes=5)

    service = followup(outbox)
    for _ in range(settings.notification_max_attempts):
        frozen_clock.advance(hours=2)
        service.send_pending_notifications(db_session)

    db_session.expire_all()
    assert notification.status == NotificationStatus.FAILED
    assert notification.attempts == settings.notification_max_attempts
    assert "SMTP connection refused" in notification.error_message


def test_transient_email_failure_recovers(client, db_session, make_professional, outbox, frozen_clock):
    outbox.failures_left = 1
    confirmed_booking(client, db_session, make_professional)

    frozen_clock.advance(minutes=6)
    followup(outbox).send_pending_notifications(db_session)

    assert len(outbox.sent) == 1
    assert db_session.scalars(select(Notification)).one().status == NotificationStatus.SENT


def test_emails_are_skipped_when_smtp_is_not_configured(client, db_session, make_professional, outbox):
    outbox.configured = False

    confirmed_booking(client, db_session, make_professional)

    notification = db_session.scalars(select(Notification)).one()
    assert notification.status == NotificationStatus.SKIPPED
    assert notification.error_message == "SMTP no configurado"


def test_staff_cancellation_notifies_the_patient(client, db_session, make_professional, outbox, auth_headers):
    appointment = confirmed_booking(client, db_session, make_professional)

    client.post(f"/api/v1/appointments/{appointment.id}/cancel", json={}, headers=auth_headers)

    assert [email["subject"] for email in outbox.sent] == ["Turno confirmado: 30/03 09:00 h", "Turno cancelado: 30/03 09:00 h"]


def test_abandoned_hold_does_not_email_the_patient(client, db_session, make_professional, outbox):
    professional_id = make_professional()
    book(client, professional_id, starts_at="2026-03-30T09:00:00")

    book(client, professional_id, starts_at="2026-03-30T10:00:00")

    assert outbox.sent == []


# --------------------------------------------------------------------------- reminders


def test_reminders_are_queued_once_per_channel(client, db_session, make_professional, outbox, whatsapp, frozen_clock):
    confirmed_booking(client, db_session, make_professional)
    frozen_clock.set(datetime(2026, 3, 29, 10, 0))
    service = followup(outbox, whatsapp)

    assert service.prepare_upcoming_reminders(db_session) == 2
    assert service.prepare_upcoming_reminders(db_session) == 0
    service.send_pending_notifications(db_session)

    template = whatsapp.messages[0]
    assert template["to"] == "5491155555555"
    assert template["template"]["name"] == "recordatorio_turno"
    assert [p["text"] for p in template["template"]["components"][0]["parameters"]] == [
        "Lucía",
        "lunes 30 de marzo",
        "09:00",
        "Laura Gómez",
    ]
    token = db_session.scalars(select(Appointment)).one().public_token
    assert template["template"]["components"][1]["parameters"][0]["payload"] == f"CONFIRM:{token}"
    assert template["template"]["components"][2]["parameters"][0]["payload"] == f"CANCEL:{token}"
    reminder = db_session.scalars(
        select(Notification).where(Notification.channel == NotificationChannel.WHATSAPP)
    ).one()
    assert reminder.provider_message_id == "wamid.OUT1"
    assert outbox.sent[-1]["subject"] == "Recordatorio de tu turno: 30/03 09:00 h"


def test_no_reminders_for_unpaid_or_far_appointments(client, db_session, make_professional, outbox, frozen_clock):
    professional_id = make_professional()
    book(client, professional_id)  # pending payment

    assert followup(outbox).prepare_upcoming_reminders(db_session, hours_ahead=168) == 0


def test_rescheduling_discards_pending_reminders(client, db_session, make_professional, outbox, auth_headers, frozen_clock):
    appointment = confirmed_booking(client, db_session, make_professional)
    frozen_clock.set(datetime(2026, 3, 29, 12, 0))
    followup(outbox).prepare_upcoming_reminders(db_session)
    db_session.query(Notification).filter(Notification.type == NotificationType.REMINDER).update(
        {"scheduled_for": datetime(2026, 3, 29, 23, 0)}
    )
    db_session.commit()

    client.post(
        f"/api/v1/appointments/{appointment.id}/reschedule",
        json={"starts_at": "2026-03-30T11:00:00"},
        headers=auth_headers,
    )

    db_session.expire_all()
    reminder = db_session.scalars(select(Notification).where(Notification.type == NotificationType.REMINDER)).one()
    assert reminder.status == NotificationStatus.SKIPPED
    assert followup(outbox).prepare_upcoming_reminders(db_session) == 1


def test_scheduled_job_expires_holds_prepares_and_sends(client, db_session, make_professional, outbox, frozen_clock):
    professional_id = make_professional(deposit=Decimal("0"))
    book(client, professional_id, starts_at="2026-03-30T09:00:00")
    paid_professional = make_professional(name="Pedro")
    book(client, paid_professional, starts_at="2026-03-30T10:00:00", dni="40111222", first_name="Juan", last_name="Díaz")
    frozen_clock.set(datetime(2026, 3, 29, 10, 0))

    summary = run_scheduled.run(followup(outbox))

    assert summary["expired_holds"] == 1
    assert summary["reminders_prepared"] == 1
    assert summary["sent"] == 1
    db_session.expire_all()
    statuses = sorted(a.status.value for a in db_session.scalars(select(Appointment)))
    assert statuses == ["expired", "reserved"]


# --------------------------------------------------------------------------- WhatsApp bot


def test_webhook_verification_handshake(client, whatsapp):
    ok = client.get("/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "42"})
    bad = client.get("/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "42"})

    assert ok.status_code == 200 and ok.text == "42"
    assert bad.status_code == 403


def test_unsigned_webhooks_are_rejected(client, db_session, make_professional, whatsapp):
    appointment = confirmed_booking(client, db_session, make_professional)

    response = webhook(client, button_message(appointment, "CONFIRM"), secret="forged")

    assert response.status_code == 401
    db_session.expire_all()
    assert appointment.attendance_confirmed_at is None


def test_patient_confirms_attendance_from_the_reminder(client, db_session, make_professional, whatsapp, frozen_clock):
    appointment = confirmed_booking(client, db_session, make_professional)

    response = webhook(client, button_message(appointment, "CONFIRM"))

    assert response.status_code == 200
    db_session.expire_all()
    assert appointment.attendance_confirmed_at == frozen_clock.now()
    assert whatsapp.texts() == ["¡Gracias, Lucía! Te esperamos el lunes 30 de marzo a las 09:00 h con Laura Gómez."]


def test_cancelling_from_whatsapp_requires_a_second_tap(client, db_session, make_professional, whatsapp, outbox):
    appointment = confirmed_booking(client, db_session, make_professional)

    webhook(client, button_message(appointment, "CANCEL", message_id="wamid.IN1"))
    db_session.expire_all()
    assert appointment.status == AppointmentStatus.CONFIRMED
    question = whatsapp.messages[-1]
    assert question["type"] == "interactive"
    assert [b["reply"]["id"] for b in question["interactive"]["action"]["buttons"]] == [
        f"CANCEL_OK:{appointment.public_token}",
        f"KEEP:{appointment.public_token}",
    ]

    webhook(client, button_message(appointment, "CANCEL_OK", message_id="wamid.IN2", kind="interactive"))

    db_session.expire_all()
    assert appointment.status == AppointmentStatus.CANCELLED
    assert "Cancelado por el paciente (whatsapp)." in appointment.notes
    assert whatsapp.texts()[-1].startswith("Listo, cancelamos tu turno del lunes 30 de marzo")
    assert outbox.sent[-1]["subject"] == "Turno cancelado: 30/03 09:00 h"


def test_whatsapp_cancellation_respects_the_notice_period(client, db_session, make_professional, whatsapp, frozen_clock):
    appointment = confirmed_booking(client, db_session, make_professional)
    frozen_clock.set(datetime(2026, 3, 29, 20, 0))  # 13 hours before

    webhook(client, button_message(appointment, "CANCEL_OK", kind="interactive"))

    db_session.expire_all()
    assert appointment.status == AppointmentStatus.CONFIRMED
    assert "Faltan menos de 24 horas" in whatsapp.texts()[-1]


def test_redelivered_webhooks_are_answered_once(client, db_session, make_professional, whatsapp):
    appointment = confirmed_booking(client, db_session, make_professional)
    payload = button_message(appointment, "KEEP", kind="interactive")

    webhook(client, payload)
    webhook(client, payload)

    assert len(whatsapp.texts()) == 1


def test_actions_from_another_number_are_ignored(client, db_session, make_professional, whatsapp):
    appointment = confirmed_booking(client, db_session, make_professional)

    webhook(client, button_message(appointment, "CANCEL_OK", sender="5491199999999", kind="interactive"))

    db_session.expire_all()
    assert appointment.status == AppointmentStatus.CONFIRMED
    assert "canal automático" in whatsapp.texts()[-1]


def test_free_text_gets_the_help_message(client, whatsapp):
    payload = {"entry": [{"changes": [{"value": {"messages": [{"from": "5491155555555", "id": "wamid.X", "type": "text", "text": {"body": "hola"}}]}}]}]}

    webhook(client, payload)

    assert "canal automático" in whatsapp.texts()[0]


def test_failed_delivery_status_marks_the_notification(client, db_session, make_professional, outbox, whatsapp, frozen_clock):
    confirmed_booking(client, db_session, make_professional)
    frozen_clock.set(datetime(2026, 3, 29, 10, 0))
    service = followup(outbox, whatsapp)
    service.prepare_upcoming_reminders(db_session)
    service.send_pending_notifications(db_session)

    webhook(
        client,
        {"entry": [{"changes": [{"value": {"statuses": [{"id": "wamid.OUT1", "status": "failed", "errors": [{"code": 131026, "title": "Message undeliverable"}]}]}}]}]},
    )

    db_session.expire_all()
    reminder = db_session.scalars(select(Notification).where(Notification.channel == NotificationChannel.WHATSAPP)).one()
    assert reminder.status == NotificationStatus.FAILED
    assert reminder.error_message == "WhatsApp: Message undeliverable"


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [("5491155555555", "+54 9 11 5555-5555", True), ("541155555555", "+5491155555555", True), ("5491155555555", "5491155555556", False), (None, "1", False)],
)
def test_whatsapp_number_matching_ignores_the_argentine_nine(first, second, expected):
    assert same_whatsapp_number(first, second) is expected


# --------------------------------------------------------------------------- self-service cancel link


def test_patient_can_cancel_from_the_booking_link(client, db_session, make_professional, outbox):
    appointment = confirmed_booking(client, db_session, make_professional)

    response = client.post(f"/reservar/turno/{appointment.public_token}/cancelar", follow_redirects=False)

    assert "Cancelamos+tu+turno" in response.headers["location"]
    db_session.expire_all()
    assert appointment.status == AppointmentStatus.CANCELLED
    assert outbox.sent[-1]["subject"].startswith("Turno cancelado")


def test_cancel_link_is_blocked_inside_the_notice_period(client, db_session, make_professional, frozen_clock):
    appointment = confirmed_booking(client, db_session, make_professional)
    frozen_clock.set(datetime(2026, 3, 29, 20, 0))

    page = client.get(f"/reservar/turno/{appointment.public_token}")
    response = client.post(f"/reservar/turno/{appointment.public_token}/cancelar")

    assert "Faltan menos de 24 horas" in page.text
    assert "Faltan menos de 24 horas" in response.text
    db_session.expire_all()
    assert appointment.status == AppointmentStatus.CONFIRMED


def test_confirmation_email_carries_the_logo_inside_the_message(client, db_session, make_professional, outbox):
    """Gmail and Outlook block remote images, so a linked logo would show up broken."""
    from email.message import EmailMessage

    from app.core.config import Settings
    from app.integrations.email import LOGO_CID, LOGO_PATH, EmailClient

    confirmed_booking(client, db_session, make_professional)
    assert f'src="cid:{LOGO_CID}"' in outbox.sent[0]["html"]
    assert LOGO_PATH.exists()

    message = EmailMessage()
    message.set_content(outbox.sent[0]["text"])
    message.add_alternative(outbox.sent[0]["html"], subtype="html")
    EmailClient(Settings(smtp_host="localhost", email_from="turnos@oral.test"))._attach_logo(message)

    images = [part for part in message.walk() if part.get_content_type() == "image/png"]
    assert [part["Content-ID"] for part in images] == [f"<{LOGO_CID}>"]


def test_moving_an_appointment_tells_the_patient_the_new_date(client, db_session, make_professional, outbox, auth_headers):
    """Without this the patient turns up at the old time: only reminders were being discarded."""
    appointment = confirmed_booking(client, db_session, make_professional)
    outbox.sent.clear()

    client.post(
        f"/api/v1/appointments/{appointment.id}/reschedule",
        json={"starts_at": "2026-03-30T11:00:00"},
        headers=auth_headers,
    )

    assert len(outbox.sent) == 1
    email = outbox.sent[0]
    assert "Cambiamos tu turno" in email["subject"]
    assert "11:00" in email["text"]
    assert "09:00" in email["text"]  # el horario viejo, para que vea qué cambió


def test_moving_a_cancelled_appointment_does_not_email_the_patient(client, db_session, make_professional, outbox, auth_headers):
    appointment = confirmed_booking(client, db_session, make_professional)
    client.post(f"/api/v1/appointments/{appointment.id}/cancel", json={}, headers=auth_headers)
    outbox.sent.clear()

    client.post(
        f"/api/v1/appointments/{appointment.id}/reschedule",
        json={"starts_at": "2026-03-30T11:00:00"},
        headers=auth_headers,
    )

    assert outbox.sent == []


# --------------------------------------------------------------------------- lista de espera


def _join_waitlist(client, professional_id=None, dni="41999888", **overrides):
    data = {
        "professional_id": str(professional_id) if professional_id else "",
        "date_from": "2026-03-28", "date_to": "2026-04-05", "period": "any",
        "dni": dni, "first_name": "Rocío", "last_name": "Paz",
        "email": f"{dni}@example.com", "phone": "11 4444-4444",
        **overrides,
    }
    return client.post("/reservar/lista-de-espera", data=data, follow_redirects=False)


def test_cancelling_an_appointment_offers_the_slot_to_the_waitlist(client, db_session, make_professional, outbox, auth_headers):
    appointment = confirmed_booking(client, db_session, make_professional)
    _join_waitlist(client, appointment.professional_id)
    outbox.sent.clear()

    client.post(f"/api/v1/appointments/{appointment.id}/cancel", json={}, headers=auth_headers)

    offers = [email for email in outbox.sent if "Se liberó un turno" in email["subject"]]
    assert len(offers) == 1
    assert offers[0]["to"] == "41999888@example.com"
    assert "Lunes 30 de marzo" in offers[0]["text"]
    entry = db_session.scalars(select(WaitlistEntry)).one()
    assert entry.status == WaitlistStatus.NOTIFIED
    assert entry.notified_slot_at == appointment.starts_at


def test_a_slot_outside_the_requested_range_is_not_offered(client, db_session, make_professional, outbox, auth_headers):
    appointment = confirmed_booking(client, db_session, make_professional)
    _join_waitlist(client, appointment.professional_id, date_from="2026-05-01", date_to="2026-05-30")
    outbox.sent.clear()

    client.post(f"/api/v1/appointments/{appointment.id}/cancel", json={}, headers=auth_headers)

    assert [email for email in outbox.sent if "Se liberó" in email["subject"]] == []
    assert db_session.scalars(select(WaitlistEntry)).one().status == WaitlistStatus.WAITING


def test_an_afternoon_only_entry_is_not_offered_a_morning_slot(client, db_session, make_professional, outbox, auth_headers):
    appointment = confirmed_booking(client, db_session, make_professional)  # 09:00
    _join_waitlist(client, appointment.professional_id, period="afternoon")
    outbox.sent.clear()

    client.post(f"/api/v1/appointments/{appointment.id}/cancel", json={}, headers=auth_headers)

    assert [email for email in outbox.sent if "Se liberó" in email["subject"]] == []


def test_the_patient_who_cancelled_is_not_offered_their_own_slot(client, db_session, make_professional, outbox, auth_headers):
    appointment = confirmed_booking(client, db_session, make_professional)
    _join_waitlist(client, appointment.professional_id, dni="30555111", first_name="Lucía", last_name="O'Connor")
    outbox.sent.clear()

    client.post(f"/api/v1/appointments/{appointment.id}/cancel", json={}, headers=auth_headers)

    assert [email for email in outbox.sent if "Se liberó" in email["subject"]] == []


def test_joining_the_waitlist_twice_updates_the_entry_instead_of_duplicating(client, db_session, make_professional):
    professional_id = make_professional()
    _join_waitlist(client, professional_id)

    _join_waitlist(client, professional_id, date_to="2026-04-20", period="morning")

    entry = db_session.scalars(select(WaitlistEntry)).one()
    assert (entry.date_to.isoformat(), entry.period) == ("2026-04-20", WaitlistPeriod.MORNING)


def test_a_series_sends_one_email_with_every_date(client, db_session, make_professional, outbox, auth_headers):
    """Doce confirmaciones seguidas son spam: va un solo mensaje con la lista."""
    from datetime import time as time_of_day

    from app.models.availability_window import AvailabilityWindow
    from app.models.patient import Patient

    professional_id = make_professional(deposit=Decimal("0"))
    patient = Patient(dni="41333222", first_name="Tomás", last_name="Ruiz", email="tomas@example.com")
    db_session.add(patient)
    for day in (date(2026, 4, 27), date(2026, 5, 25)):
        db_session.add(
            AvailabilityWindow(
                professional_id=professional_id, availability_date=day,
                start_time=time_of_day(9, 0), end_time=time_of_day(12, 0), slot_duration_minutes=30,
            )
        )
    db_session.commit()

    client.post(
        "/api/v1/appointments/series",
        json={
            "patient_id": patient.id, "professional_id": professional_id,
            "starts_at": "2026-03-30T09:00:00", "every_weeks": 4, "occurrences": 3,
        },
        headers=auth_headers,
    )

    assert len(outbox.sent) == 1
    body = outbox.sent[0]["text"]
    assert "Lunes 30 de marzo" in body
    assert "Lunes 27 de abril" in body
    assert "Lunes 25 de mayo" in body


def test_someone_waiting_for_any_professional_is_offered_the_slot(client, db_session, make_professional, outbox, auth_headers):
    """professional_id NULL es "cualquiera": con IN (id, NULL) esas filas nunca matchean."""
    appointment = confirmed_booking(client, db_session, make_professional)
    _join_waitlist(client, professional_id=None)
    outbox.sent.clear()

    client.post(f"/api/v1/appointments/{appointment.id}/cancel", json={}, headers=auth_headers)

    assert [email["subject"] for email in outbox.sent if "Se liberó" in email["subject"]]
    assert db_session.scalars(select(WaitlistEntry)).one().status == WaitlistStatus.NOTIFIED


def test_booking_the_offered_slot_closes_the_waitlist_entry(client, db_session, make_professional, outbox):
    """Si no se cierra, esa persona queda "Avisado" para siempre y sigue recibiendo ofertas."""
    professional_id = make_professional(deposit=Decimal("0"))
    _join_waitlist(client, professional_id, dni="35777666", first_name="Vera", last_name="Paz")

    book(client, professional_id, dni="35777666", first_name="Vera", last_name="Paz", email="35777666@example.com")

    db_session.expire_all()
    assert db_session.scalars(select(WaitlistEntry)).one().status == WaitlistStatus.BOOKED


def test_sin_whatsapp_configurado_el_recordatorio_sale_solo_por_email(client, db_session, make_professional, outbox, frozen_clock):
    """Perfil de lanzamiento del consultorio: email únicamente, WhatsApp se suma después."""
    confirmed_booking(client, db_session, make_professional)
    frozen_clock.set(datetime(2026, 3, 29, 10, 0))
    outbox.sent.clear()
    service = followup(outbox)  # sin cliente de WhatsApp

    assert service.prepare_upcoming_reminders(db_session) == 1
    service.send_pending_notifications(db_session)

    recordatorios = db_session.scalars(
        select(Notification).where(Notification.type == NotificationType.REMINDER)
    ).all()
    assert [n.channel for n in recordatorios] == [NotificationChannel.EMAIL]
    assert [n.status for n in recordatorios] == [NotificationStatus.SENT]
    assert "Recordatorio" in outbox.sent[-1]["subject"]


def test_the_waitlist_validates_identity_like_the_booking_form(client, db_session, make_professional):
    """La lista de espera arma PatientIdentity con el formulario crudo.

    Sin validarla, un DNI o un nombre inventados creaban una ficha de paciente nueva
    en cada intento, algo que /reservar sí rechazaba.
    """
    professional_id = make_professional()
    for campo, valor in (("dni", "123"), ("first_name", "R0cío"), ("last_name", "P4z")):
        campos = {"dni": "41777666", campo: valor}
        response = _join_waitlist(client, professional_id, **campos)

        assert "error=" in response.headers["location"], f"aceptó {campo}={valor!r}"
    assert db_session.scalars(select(Patient)).all() == []


# ------------------------------------------------------------------ avisos al profesional

PROFESSIONAL_EMAIL = "nazarena@example.com"
PATIENT_EMAIL = "lucia@example.com"


def with_email(db_session, professional_id: int, email: str = PROFESSIONAL_EMAIL) -> None:
    from app.models.professional import Professional

    db_session.get(Professional, professional_id).email = email
    db_session.commit()


def notices(outbox) -> list[dict]:
    """Lo que recibió el profesional, sin los mensajes al paciente."""
    return [message for message in outbox.sent if message["to"] == PROFESSIONAL_EMAIL]


def make_appointment(
    db_session, professional_id, *, starts_at, status=AppointmentStatus.RESERVED,
    dni="30555111", first_name="Lucía", last_name="O'Connor",
) -> Appointment:
    patient = db_session.scalar(select(Patient).where(Patient.dni == dni))
    if patient is None:
        patient = Patient(dni=dni, first_name=first_name, last_name=last_name, email=PATIENT_EMAIL, phone="+5491155555555")
        db_session.add(patient)
        db_session.flush()
    appointment = Appointment(
        patient_id=patient.id, professional_id=professional_id, starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=30), duration_minutes=30, status=status, created_by="test",
    )
    db_session.add(appointment)
    db_session.commit()
    return appointment


def test_an_online_booking_emails_the_professional(client, db_session, make_professional, outbox):
    professional_id = make_professional(deposit=Decimal("0"), name="Nazarena")
    with_email(db_session, professional_id)

    book(client, professional_id, starts_at="2026-03-30T09:00:00")

    [aviso] = notices(outbox)
    assert aviso["subject"] == "Nuevo turno: Lucía O'Connor, 30/03 09:00 h"
    assert "Lunes 30 de marzo" in aviso["text"] and "09:00" in aviso["text"]
    assert "/app" in aviso["text"]
    # Solo lo mínimo: ni DNI, ni teléfono, ni email del paciente, en ninguna de las dos versiones.
    for contenido in (aviso["text"], aviso["html"]):
        for privado in ("30555111", "5555-5555", "11 5555", PATIENT_EMAIL):
            assert privado not in contenido
    # El paciente sigue recibiendo su propia confirmación.
    assert any(message["to"] == PATIENT_EMAIL for message in outbox.sent)


def test_a_professional_without_email_gets_no_notices(client, db_session, make_professional, outbox):
    professional_id = make_professional(deposit=Decimal("0"))

    response = book(client, professional_id, starts_at="2026-03-30T09:00:00")

    assert response.status_code == 303
    assert [message["to"] for message in outbox.sent] == [PATIENT_EMAIL]


def test_an_unpaid_hold_does_not_email_the_professional_until_paid(client, db_session, make_professional, outbox):
    professional_id = make_professional(name="Nazarena")  # con seña por defecto
    with_email(db_session, professional_id)

    checkout = book(client, professional_id, starts_at="2026-03-30T09:00:00").headers["location"]
    assert notices(outbox) == []

    client.post(checkout, data={"decision": "approve"})

    assert [aviso["subject"] for aviso in notices(outbox)] == ["Nuevo turno: Lucía O'Connor, 30/03 09:00 h"]


def test_a_counter_booking_emails_the_professional(client, db_session, make_professional, outbox, auth_headers):
    professional_id = make_professional(deposit=Decimal("0"), name="Nazarena")
    with_email(db_session, professional_id)
    patient = Patient(dni="41333222", first_name="Tomás", last_name="Ruiz", email="tomas@example.com")
    db_session.add(patient)
    db_session.commit()

    client.post(
        "/api/v1/appointments/",
        json={"patient_id": patient.id, "professional_id": professional_id, "starts_at": "2026-03-30T10:00:00"},
        headers=auth_headers,
    )

    assert [aviso["subject"] for aviso in notices(outbox)] == ["Nuevo turno: Tomás Ruiz, 30/03 10:00 h"]


def test_a_series_sends_the_professional_a_single_notice(client, db_session, make_professional, outbox, auth_headers):
    from datetime import time as time_of_day

    from app.models.availability_window import AvailabilityWindow

    professional_id = make_professional(deposit=Decimal("0"), name="Nazarena")
    with_email(db_session, professional_id)
    patient = Patient(dni="41333222", first_name="Tomás", last_name="Ruiz", email="tomas@example.com")
    db_session.add(patient)
    for day in (date(2026, 4, 27), date(2026, 5, 25)):
        db_session.add(
            AvailabilityWindow(
                professional_id=professional_id, availability_date=day,
                start_time=time_of_day(9, 0), end_time=time_of_day(12, 0), slot_duration_minutes=30,
            )
        )
    db_session.commit()

    client.post(
        "/api/v1/appointments/series",
        json={"patient_id": patient.id, "professional_id": professional_id,
              "starts_at": "2026-03-30T09:00:00", "every_weeks": 4, "occurrences": 3},
        headers=auth_headers,
    )

    [aviso] = notices(outbox)
    assert aviso["subject"] == "Nuevos turnos: Tomás Ruiz (3), desde 30/03 09:00 h"
    for fecha in ("Lunes 30 de marzo", "Lunes 27 de abril", "Lunes 25 de mayo"):
        assert fecha in aviso["text"]


def test_cancelling_tells_the_professional(client, db_session, make_professional, outbox, auth_headers):
    professional_id = make_professional(deposit=Decimal("0"), name="Nazarena")
    with_email(db_session, professional_id)
    book(client, professional_id, starts_at="2026-03-30T09:00:00")
    appointment = db_session.scalars(select(Appointment)).one()

    client.post(f"/api/v1/appointments/{appointment.id}/cancel", json={}, headers=auth_headers)

    assert [aviso["subject"] for aviso in notices(outbox)] == [
        "Nuevo turno: Lucía O'Connor, 30/03 09:00 h",
        "Turno cancelado: Lucía O'Connor, 30/03 09:00 h",
    ]


def test_cancelling_before_the_new_booking_notice_goes_out_sends_neither(db_session, make_professional, outbox):
    """Si el profesional nunca se enteró del turno, no tiene por qué enterarse de que se canceló."""
    professional_id = make_professional(name="Nazarena")
    with_email(db_session, professional_id)
    appointment = make_appointment(db_session, professional_id, starts_at=datetime(2026, 3, 30, 9, 0))
    service = followup(outbox)

    service.queue_professional_booking(db_session, appointment)
    db_session.commit()
    assert service.queue_professional_cancellation(db_session, appointment) is None
    db_session.commit()
    service.send_pending_notifications(db_session)

    assert outbox.sent == []
    [fila] = db_session.scalars(select(Notification)).all()
    assert fila.status == NotificationStatus.SKIPPED


def test_rescheduling_tells_the_professional_both_times(client, db_session, make_professional, outbox, auth_headers):
    professional_id = make_professional(deposit=Decimal("0"), name="Nazarena")
    with_email(db_session, professional_id)
    book(client, professional_id, starts_at="2026-03-30T09:00:00")
    appointment = db_session.scalars(select(Appointment)).one()
    outbox.sent.clear()

    client.post(
        f"/api/v1/appointments/{appointment.id}/reschedule",
        json={"starts_at": "2026-03-30T11:00:00"},
        headers=auth_headers,
    )

    [aviso] = notices(outbox)
    assert aviso["subject"] == "Turno movido: Lucía O'Connor, ahora 30/03 11:00 h"
    assert "09:00" in aviso["text"] and "11:00" in aviso["text"]


def test_confirming_a_reserved_appointment_does_not_notify_the_professional(
    client, db_session, make_professional, outbox, auth_headers
):
    professional_id = make_professional(deposit=Decimal("0"), name="Nazarena")
    with_email(db_session, professional_id)
    book(client, professional_id, starts_at="2026-03-30T09:00:00")
    appointment = db_session.scalars(select(Appointment)).one()

    client.post(f"/api/v1/appointments/{appointment.id}/confirm", json={}, headers=auth_headers)

    assert len(notices(outbox)) == 1  # solo el de turno nuevo


def test_the_evening_digest_lists_tomorrows_appointments_once(db_session, make_professional, outbox, frozen_clock):
    professional_id = make_professional(name="Nazarena")
    with_email(db_session, professional_id)
    sabado = datetime(2026, 3, 28, 9, 0)
    make_appointment(db_session, professional_id, starts_at=sabado)
    make_appointment(db_session, professional_id, starts_at=sabado + timedelta(minutes=30),
                     status=AppointmentStatus.CONFIRMED, dni="30111222", first_name="Ana", last_name="Pérez")
    make_appointment(db_session, professional_id, starts_at=sabado + timedelta(hours=1),
                     status=AppointmentStatus.CANCELLED, dni="30333444", first_name="Bruno", last_name="Díaz")
    make_appointment(db_session, professional_id, starts_at=sabado + timedelta(days=1), dni="30555999",
                     first_name="Carla", last_name="Ruiz")
    frozen_clock.set(datetime(2026, 3, 27, 18, 0))
    service = followup(outbox)

    assert service.prepare_professional_digests(db_session) == 1
    assert service.prepare_professional_digests(db_session) == 0
    service.send_pending_notifications(db_session)

    [aviso] = notices(outbox)
    assert aviso["subject"] == "Tu agenda de mañana: sábado 28 de marzo (2 turnos)"
    texto = aviso["text"]
    assert texto.index("Lucía O'Connor") < texto.index("Ana Pérez")
    assert "Bruno" not in texto and "Carla" not in texto  # cancelado, y otro día
    assert "30555111" not in texto


def test_the_digest_is_not_sent_early_empty_or_without_email(db_session, make_professional, outbox, frozen_clock, monkeypatch):
    con_email = make_professional(name="Nazarena")
    with_email(db_session, con_email)
    sin_email = make_professional(name="Sabina")
    make_appointment(db_session, sin_email, starts_at=datetime(2026, 3, 28, 9, 0), dni="30111222",
                     first_name="Ana", last_name="Pérez")
    service = followup(outbox)

    frozen_clock.set(datetime(2026, 3, 27, 17, 59))
    make_appointment(db_session, con_email, starts_at=datetime(2026, 3, 28, 9, 0))
    assert service.prepare_professional_digests(db_session) == 0  # todavía no es la hora

    frozen_clock.set(datetime(2026, 3, 27, 18, 0))
    assert service.prepare_professional_digests(db_session) == 1  # solo quien tiene email y turnos
    db_session.query(Notification).delete()
    db_session.commit()

    frozen_clock.set(datetime(2026, 3, 28, 18, 0))  # el domingo no hay turnos
    assert service.prepare_professional_digests(db_session) == 0

    monkeypatch.setattr(settings, "professional_digest_hour", 20)
    frozen_clock.set(datetime(2026, 3, 27, 19, 0))
    assert service.prepare_professional_digests(db_session) == 0  # la hora es configurable


def test_the_scheduled_job_prepares_the_digests(db_session, make_professional, outbox, frozen_clock):
    professional_id = make_professional(name="Nazarena")
    with_email(db_session, professional_id)
    make_appointment(db_session, professional_id, starts_at=datetime(2026, 3, 28, 9, 0))
    frozen_clock.set(datetime(2026, 3, 27, 18, 0))

    summary = run_scheduled.run(followup(outbox))

    assert summary["digests_prepared"] == 1
    assert [aviso["subject"] for aviso in notices(outbox)] == ["Tu agenda de mañana: sábado 28 de marzo (1 turno)"]


def test_every_notification_type_has_a_label_and_fits_the_column():
    from app.core.enums import NOTIFICATION_TYPE_LABELS

    for tipo in NotificationType:
        assert tipo in NOTIFICATION_TYPE_LABELS, f"{tipo.value} no tiene etiqueta en el panel"
        # La columna es VARCHAR(20): un valor más largo falla recién en producción (PostgreSQL).
        assert len(tipo.value) <= 20, tipo.value


def test_the_panel_flows_notify_the_professional(client, db_session, make_professional, outbox):
    """Recorre lo que hace recepción en el panel y comprueba, paso a paso, qué recibe el profesional."""
    from app.core.enums import UserRole
    from tests.conftest import create_user

    professional_id = make_professional(deposit=Decimal("0"), name="Nazarena")
    with_email(db_session, professional_id)
    create_user(db_session, username="recepcion", role=UserRole.RECEPTIONIST)
    patient = Patient(dni="41333222", first_name="Tomás", last_name="Ruiz", email="tomas@example.com")
    db_session.add(patient)
    db_session.commit()
    client.post("/app/login", data={"username": "recepcion", "password": "demo12345"}, follow_redirects=False)

    def asuntos() -> list[str]:
        return [aviso["subject"] for aviso in notices(outbox)]

    client.post(
        "/app/appointments",
        data={"patient_id": str(patient.id), "professional_id": str(professional_id),
              "starts_at": "2026-03-30T09:00", "duration_minutes": "30", "reason": "Control"},
        follow_redirects=False,
    )
    assert asuntos() == ["Nuevo turno: Tomás Ruiz, 30/03 09:00 h"]
    turno = db_session.scalars(select(Appointment)).one()

    client.post(
        f"/app/appointments/{turno.id}/edit",
        data={"starts_at": "2026-03-30T10:00", "duration_minutes": "30", "status": "reserved", "reason": "Control"},
        follow_redirects=False,
    )
    assert asuntos()[-1] == "Turno movido: Tomás Ruiz, ahora 30/03 10:00 h"

    client.post(f"/app/appointments/{turno.id}/status", data={"action": "cancel"}, follow_redirects=False)
    assert asuntos()[-1] == "Turno cancelado: Tomás Ruiz, 30/03 10:00 h"

    client.post(f"/app/appointments/{turno.id}/status", data={"action": "reserve"}, follow_redirects=False)
    assert asuntos()[-1] == "Nuevo turno: Tomás Ruiz, 30/03 10:00 h"  # vuelve a la agenda: es noticia

    cantidad = len(asuntos())
    client.post(f"/app/appointments/{turno.id}/status", data={"action": "confirm"}, follow_redirects=False)
    assert len(asuntos()) == cantidad  # confirmar un turno que ya estaba reservado no avisa
    assert cantidad == 4
