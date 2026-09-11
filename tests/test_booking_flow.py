"""Public booking end to end: hold, deposit checkout (simulator), expiry and validations."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.enums import AppointmentStatus, NotificationType, PaymentStatus
from app.models.appointment import Appointment
from app.models.availability_window import AvailabilityWindow
from app.models.notification import Notification
from app.models.patient import Patient
from app.models.professional import Professional

MONDAY = date(2026, 3, 30)
settings = get_settings()


@pytest.fixture()
def make_professional(db_session):
    def factory(*, deposit: Decimal | None = Decimal("10000"), days=(MONDAY,), name="Laura") -> int:
        professional = Professional(
            first_name=name,
            last_name="Gómez",
            specialty="General",
            default_appointment_duration=30,
            deposit_amount=deposit,
        )
        db_session.add(professional)
        db_session.flush()
        for day in days:
            db_session.add(
                AvailabilityWindow(
                    professional_id=professional.id,
                    availability_date=day,
                    start_time=time(9, 0),
                    end_time=time(12, 0),
                    slot_duration_minutes=30,
                )
            )
        db_session.commit()
        return professional.id

    return factory


def booking_form(professional_id: int, starts_at: str = "2026-03-30T09:00:00", **overrides) -> dict:
    data = {
        "professional_id": str(professional_id),
        "starts_at": starts_at,
        "dni": "30555111",
        "first_name": "Lucía",
        "last_name": "Fernández",
        "email": "lucia@example.com",
        "phone": "11 5555-5555",
        "reason": "Control",
        "observations": "",
        "accept_terms": "1",
        "website": "",
    }
    data.update(overrides)
    return data


def book(client, professional_id, **overrides):
    return client.post("/reservar", data=booking_form(professional_id, **overrides), follow_redirects=False)


def only_appointment(db_session) -> Appointment:
    db_session.expire_all()
    return db_session.scalars(select(Appointment)).one()


def test_booking_with_deposit_holds_slot_and_sends_patient_to_checkout(client, db_session, make_professional, frozen_clock):
    professional_id = make_professional()

    response = book(client, professional_id)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/pagos/simulador/")
    appointment = only_appointment(db_session)
    assert appointment.status == AppointmentStatus.PENDING_PAYMENT
    assert appointment.hold_expires_at == frozen_clock.now() + timedelta(minutes=settings.booking_hold_minutes)
    assert appointment.deposit_amount == Decimal("10000.00")
    assert appointment.contact_phone == "+5491155555555"
    assert appointment.latest_payment.status == PaymentStatus.PENDING

    page = client.get(f"/reservar?professional_id={professional_id}&selected_date=2026-03-30")
    assert 'value="2026-03-30T09:00:00"' not in page.text
    assert 'value="2026-03-30T09:30:00"' in page.text


def test_approved_deposit_confirms_the_appointment(client, db_session, make_professional):
    professional_id = make_professional()
    checkout_url = book(client, professional_id).headers["location"]

    response = client.post(checkout_url, data={"decision": "approve"}, follow_redirects=False)

    appointment = only_appointment(db_session)
    assert response.headers["location"] == f"/reservar/turno/{appointment.public_token}"
    assert appointment.status == AppointmentStatus.CONFIRMED
    assert appointment.hold_expires_at is None
    assert appointment.latest_payment.status == PaymentStatus.APPROVED
    confirmation = db_session.scalars(
        select(Notification).where(Notification.type == NotificationType.CONFIRMATION)
    ).one()
    assert confirmation.recipient == "lucia@example.com"
    assert "Te esperamos" in client.get(response.headers["location"]).text


def test_rejected_deposit_keeps_the_hold_and_offers_a_retry(client, db_session, make_professional):
    professional_id = make_professional()
    checkout_url = book(client, professional_id).headers["location"]

    client.post(checkout_url, data={"decision": "reject"})

    appointment = only_appointment(db_session)
    assert appointment.status == AppointmentStatus.PENDING_PAYMENT
    status_page = client.get(f"/reservar/turno/{appointment.public_token}")
    assert "Reintentar el pago" in status_page.text
    retry = client.post(f"/reservar/turno/{appointment.public_token}/pagar", follow_redirects=False)
    assert retry.headers["location"] == checkout_url


def test_unpaid_hold_expires_and_the_slot_is_released(client, db_session, make_professional, frozen_clock):
    professional_id = make_professional()
    book(client, professional_id)
    first = only_appointment(db_session)

    frozen_clock.advance(minutes=settings.booking_hold_minutes + 1)
    status_page = client.get(f"/reservar/turno/{first.public_token}")

    assert "El horario se liberó" in status_page.text
    db_session.expire_all()
    assert first.status == AppointmentStatus.EXPIRED
    assert first.latest_payment.status == PaymentStatus.EXPIRED
    second = book(client, professional_id, dni="40111222", first_name="Juan", last_name="Díaz")
    assert second.status_code == 303


def test_late_payment_for_a_slot_taken_meanwhile_is_flagged_for_refund(
    client, db_session, make_professional, frozen_clock, auth_headers
):
    professional_id = make_professional()
    late_checkout = book(client, professional_id).headers["location"]
    frozen_clock.advance(minutes=settings.booking_hold_minutes + 1)
    assert book(client, professional_id, dni="40111222", first_name="Juan", last_name="Díaz").status_code == 303

    client.post(late_checkout, data={"decision": "approve"})

    db_session.expire_all()
    late = db_session.scalars(select(Appointment).where(Appointment.status == AppointmentStatus.EXPIRED)).one()
    assert late.latest_payment.status == PaymentStatus.APPROVED
    assert "devolverte la seña" in client.get(f"/reservar/turno/{late.public_token}").text
    refunds = client.get("/api/v1/payments/requires-refund", headers=auth_headers).json()
    assert [item["appointment_id"] for item in refunds] == [late.id]


def test_late_payment_confirms_when_the_slot_is_still_free(client, db_session, make_professional, frozen_clock):
    professional_id = make_professional()
    checkout_url = book(client, professional_id).headers["location"]
    frozen_clock.advance(minutes=settings.booking_hold_minutes + 5)

    client.post(checkout_url, data={"decision": "approve"})

    assert only_appointment(db_session).status == AppointmentStatus.CONFIRMED


def test_booking_without_deposit_is_reserved_right_away(client, db_session, make_professional):
    professional_id = make_professional(deposit=Decimal("0"))

    response = book(client, professional_id)

    appointment = only_appointment(db_session)
    assert response.headers["location"] == f"/reservar/turno/{appointment.public_token}"
    assert appointment.status == AppointmentStatus.RESERVED
    assert appointment.payments == []


def test_resubmitting_the_same_slot_reuses_the_hold(client, db_session, make_professional):
    professional_id = make_professional()

    first = book(client, professional_id)
    second = book(client, professional_id)

    assert first.headers["location"] == second.headers["location"]
    assert len(db_session.scalars(select(Appointment)).all()) == 1


def test_choosing_another_slot_releases_the_previous_hold(client, db_session, make_professional):
    professional_id = make_professional()
    book(client, professional_id, starts_at="2026-03-30T09:00:00")

    book(client, professional_id, starts_at="2026-03-30T10:00:00")

    db_session.expire_all()
    statuses = {a.starts_at.time(): a.status for a in db_session.scalars(select(Appointment))}
    assert statuses == {time(9, 0): AppointmentStatus.CANCELLED, time(10, 0): AppointmentStatus.PENDING_PAYMENT}


def test_invalid_data_is_explained_and_typed_values_are_kept(client, db_session, make_professional):
    professional_id = make_professional()

    response = book(client, professional_id, dni="12.3", first_name="Lucía")

    assert response.status_code == 422
    assert "DNI válido" in response.text
    assert 'value="Lucía"' in response.text
    assert db_session.scalars(select(Appointment)).all() == []


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"accept_terms": ""}, "política de seña"),
        ({"phone": "4555-5555"}, "código de área"),
        ({"email": "sin-arroba"}, "email válido"),
        ({"starts_at": "2026-03-30T09:10:00"}, "no está disponible"),
        ({"starts_at": ""}, "Horario"),
    ],
)
def test_booking_validations(client, make_professional, overrides, expected):
    professional_id = make_professional()
    response = book(client, professional_id, **overrides)
    assert response.status_code == 422
    assert expected in response.text


def test_online_bookings_respect_minimum_lead_time(client, make_professional, frozen_clock):
    professional_id = make_professional()
    frozen_clock.set(datetime(2026, 3, 30, 8, 0))

    response = book(client, professional_id, starts_at="2026-03-30T09:00:00")

    assert response.status_code == 422
    assert "anticipación" in response.text


def test_existing_dni_with_another_last_name_is_rejected(client, db_session, make_professional):
    professional_id = make_professional()
    db_session.add(Patient(dni="30555111", first_name="Otra", last_name="Persona", email="otra@example.com"))
    db_session.commit()

    response = book(client, professional_id)

    assert response.status_code == 422
    assert "no coinciden" in response.text


def test_public_booking_never_overwrites_the_patient_record(client, db_session, make_professional):
    professional_id = make_professional(deposit=Decimal("0"))
    db_session.add(Patient(dni="30555111", first_name="Lucía", last_name="Fernández García", email="real@example.com"))
    db_session.commit()

    book(client, professional_id, email="intruso@example.com", last_name="Fernandez")

    db_session.expire_all()
    patient = db_session.scalars(select(Patient)).one()
    assert patient.email == "real@example.com"
    assert patient.phone == "+5491155555555"  # empty fields are completed
    appointment = only_appointment(db_session)
    assert appointment.contact_email == "intruso@example.com"


def test_patients_cannot_hoard_upcoming_appointments(client, make_professional, monkeypatch):
    monkeypatch.setattr(settings, "booking_max_active_per_patient", 2)
    professional_id = make_professional(deposit=Decimal("0"), days=(MONDAY, MONDAY + timedelta(days=1), MONDAY + timedelta(days=2)))
    assert book(client, professional_id, starts_at="2026-03-30T09:00:00").status_code == 303
    assert book(client, professional_id, starts_at="2026-03-31T09:00:00").status_code == 303

    response = book(client, professional_id, starts_at="2026-04-01T09:00:00")

    assert response.status_code == 422
    assert "máximo para reservar online" in response.text


def test_one_appointment_per_professional_and_day(client, make_professional):
    professional_id = make_professional(deposit=Decimal("0"))
    assert book(client, professional_id, starts_at="2026-03-30T09:00:00").status_code == 303

    response = book(client, professional_id, starts_at="2026-03-30T11:00:00")

    assert response.status_code == 422
    assert "ese día" in response.text


def test_honeypot_blocks_bots(client, db_session, make_professional):
    professional_id = make_professional()

    response = book(client, professional_id, website="http://spam.example")

    assert response.status_code == 422
    assert db_session.scalars(select(Appointment)).all() == []


def test_booking_attempts_are_rate_limited(client, make_professional, monkeypatch):
    monkeypatch.setattr(settings, "booking_rate_limit_per_hour", 2)
    professional_id = make_professional()
    for _ in range(2):
        book(client, professional_id, dni="1")

    response = book(client, professional_id)

    assert "muchos intentos" in response.text


def test_calendar_file_uses_utc_times(client, db_session, make_professional):
    professional_id = make_professional(deposit=Decimal("0"))
    book(client, professional_id)
    token = only_appointment(db_session).public_token

    response = client.get(f"/reservar/turno/{token}/calendario.ics")

    assert response.headers["content-type"].startswith("text/calendar")
    assert "DTSTART:20260330T120000Z" in response.text  # 09:00 in Buenos Aires


def test_unknown_booking_link_shows_a_friendly_page(client):
    response = client.get("/reservar/turno/no-existe")
    assert response.status_code == 404
    assert "No encontramos ese turno" in response.text


def test_payment_simulator_is_unavailable_in_production(client, db_session, make_professional, monkeypatch):
    professional_id = make_professional()
    checkout_url = book(client, professional_id).headers["location"]
    monkeypatch.setattr(settings, "app_env", "production")

    assert client.get(checkout_url).status_code == 404
    assert client.post(checkout_url, data={"decision": "approve"}).status_code == 404
