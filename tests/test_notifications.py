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
from app.models.notification import Notification
from app.models.waitlist_entry import WaitlistEntry
from app.services.followup_agent import FollowUpAgent
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


def followup(email_client, whatsapp_api: FakeWhatsAppAPI | None = None) -> FollowUpAgent:
    whatsapp_client = None
    if whatsapp_api:
        whatsapp_client = WhatsAppClient(
            settings, client=httpx.Client(base_url=GRAPH_BASE_URL, transport=httpx.MockTransport(whatsapp_api.handler))
        )
    return FollowUpAgent(settings, email_client, whatsapp_client)


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

    agent = followup(outbox)
    for _ in range(settings.notification_max_attempts):
        frozen_clock.advance(hours=2)
        agent.send_pending_notifications(db_session)

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
    agent = followup(outbox, whatsapp)

    assert agent.prepare_upcoming_reminders(db_session) == 2
    assert agent.prepare_upcoming_reminders(db_session) == 0
    agent.send_pending_notifications(db_session)

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
    agent = followup(outbox, whatsapp)
    agent.prepare_upcoming_reminders(db_session)
    agent.send_pending_notifications(db_session)

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
