"""Spec 0005: el paciente confirma su turno desde el email; si no lo hace, se entera la profesional."""

import re
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import select

from app.core.enums import AppointmentStatus, NotificationType
from app.models.appointment import Appointment
from app.models.availability_window import AvailabilityWindow
from app.models.notification import Notification
from app.tasks import run_scheduled
from tests.test_notifications import (  # noqa: F401  (outbox es un fixture)
    PATIENT_EMAIL,
    PROFESSIONAL_EMAIL,
    book,
    followup,
    notices,
    outbox,
    with_email,
)

CONFIRM_LINK = re.compile(r"(/reservar/turno/[^/\s\"]+/confirmar\?c=[A-Za-z0-9_-]+)")
MONDAY_9 = datetime(2026, 3, 30, 9, 0)


def _booked(client, db_session, make_professional, *, days=(date(2026, 3, 30),)) -> Appointment:
    """Turno online sin seña del lunes 30/03 a las 9:00, reservado el viernes: queda «reservado»."""
    professional_id = make_professional(deposit=Decimal("0"), name="Nazarena", days=days)
    with_email(db_session, professional_id)
    response = book(client, professional_id, starts_at="2026-03-30T09:00:00")
    assert response.status_code == 303, response.text[:300]
    db_session.expire_all()
    appointment = db_session.scalars(select(Appointment)).one()
    assert appointment.status == AppointmentStatus.RESERVED
    return appointment


def _to_patient(outbox) -> list[dict]:  # noqa: F811
    return [message for message in outbox.sent if message["to"] == PATIENT_EMAIL]


def _link_in(message: dict) -> str:
    links = CONFIRM_LINK.findall(message["text"])
    assert links, message["text"]
    assert links[0] in message["html"].replace("&amp;", "&")
    return links[0]


def _remind(db_session, outbox, frozen_clock, at: datetime) -> int:  # noqa: F811
    frozen_clock.set(at)
    service = followup(outbox)
    prepared = service.prepare_upcoming_reminders(db_session)
    service.send_pending_notifications(db_session)
    return prepared


def _alerts(outbox) -> list[dict]:  # noqa: F811
    """Avisos de «sin confirmar» a la profesional (a esa hora también le llega la agenda de mañana)."""
    return [message for message in notices(outbox) if message["subject"].startswith("Sin confirmar")]


def _confirm(client, link: str):
    path, _, code = link.partition("?c=")
    return client.post(path, data={"c": code}, follow_redirects=False)


def _reload(db_session, appointment: Appointment) -> Appointment:
    db_session.expire_all()
    return db_session.get(Appointment, appointment.id)


def test_the_24h_reminder_asks_the_patient_to_confirm(client, db_session, make_professional, outbox, frozen_clock):  # noqa: F811
    appointment = _booked(client, db_session, make_professional)
    [booking_email] = _to_patient(outbox)
    assert "/confirmar" not in booking_email["text"]  # faltaban más de 24 h

    assert _remind(db_session, outbox, frozen_clock, datetime(2026, 3, 29, 9, 0)) == 1

    reminder = _to_patient(outbox)[-1]
    assert reminder["subject"] == "Confirmá tu turno: 30/03 09:00 h"
    assert "Confirmar turno" in reminder["html"]
    assert _link_in(reminder).startswith(f"/reservar/turno/{appointment.public_token}/confirmar?c=")


def test_opening_the_confirmation_link_does_not_confirm_by_itself(client, db_session, make_professional, outbox, frozen_clock):  # noqa: F811
    """Outlook/Hotmail abren los links para revisarlos: abrir no puede confirmar."""
    appointment = _booked(client, db_session, make_professional)
    _remind(db_session, outbox, frozen_clock, datetime(2026, 3, 29, 9, 0))

    page = client.get(_link_in(_to_patient(outbox)[-1]))

    assert page.status_code == 200
    assert "Sí, voy a ir" in page.text
    assert "lunes 30 de marzo" in page.text.lower()
    assert _reload(db_session, appointment).status == AppointmentStatus.RESERVED


def test_the_patient_confirms_from_the_link(client, db_session, make_professional, outbox, frozen_clock):  # noqa: F811
    appointment = _booked(client, db_session, make_professional)
    _remind(db_session, outbox, frozen_clock, datetime(2026, 3, 29, 9, 0))
    sent_before = len(outbox.sent)

    response = _confirm(client, _link_in(_to_patient(outbox)[-1]))

    assert response.status_code == 303
    assert response.headers["location"].startswith(f"/reservar/turno/{appointment.public_token}")
    appointment = _reload(db_session, appointment)
    assert appointment.status == AppointmentStatus.CONFIRMED
    assert appointment.attendance_confirmed_at == datetime(2026, 3, 29, 9, 0)
    assert len(outbox.sent) == sent_before  # confirmar no dispara otro email
    page = client.get(response.headers["location"])
    assert "Confirmaste tu turno" in page.text
    # Tocar dos veces no cambia nada.
    assert _confirm(client, _link_in(_to_patient(outbox)[-1])).status_code == 303
    assert _reload(db_session, appointment).attendance_confirmed_at == datetime(2026, 3, 29, 9, 0)


def test_a_booking_inside_24h_asks_for_confirmation_right_away(client, db_session, make_professional, outbox, frozen_clock):  # noqa: F811
    frozen_clock.set(datetime(2026, 3, 29, 12, 0))
    appointment = _booked(client, db_session, make_professional)

    [booking_email] = _to_patient(outbox)
    assert "Confirmar turno" in booking_email["html"]
    assert _confirm(client, _link_in(booking_email)).status_code == 303
    assert _reload(db_session, appointment).status == AppointmentStatus.CONFIRMED
    assert _remind(db_session, outbox, frozen_clock, datetime(2026, 3, 29, 12, 10)) == 0
    assert len(_to_patient(outbox)) == 1


def test_a_manual_appointment_inside_24h_asks_for_confirmation_right_away(
    client, db_session, make_professional, outbox, frozen_clock, auth_headers  # noqa: F811
):
    from app.models.patient import Patient

    frozen_clock.set(datetime(2026, 3, 29, 12, 0))
    professional_id = make_professional(deposit=Decimal("0"), name="Nazarena")
    patient = Patient(dni="30555111", first_name="Lucía", last_name="O'Connor", email=PATIENT_EMAIL)
    db_session.add(patient)
    db_session.commit()

    response = client.post(
        "/api/v1/appointments/",
        json={"patient_id": patient.id, "professional_id": professional_id, "starts_at": "2026-03-30T10:00:00"},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    followup(outbox).send_pending_notifications(db_session)

    [email] = _to_patient(outbox)
    assert "Confirmar turno" in email["html"]


def test_the_professional_hears_about_an_unconfirmed_patient_at_12h(client, db_session, make_professional, outbox, frozen_clock):  # noqa: F811
    _booked(client, db_session, make_professional)
    _remind(db_session, outbox, frozen_clock, datetime(2026, 3, 29, 9, 0))
    outbox.sent.clear()

    frozen_clock.set(datetime(2026, 3, 29, 20, 50))
    assert run_scheduled.run(followup(outbox))["unconfirmed_alerts"] == 0  # todavía faltan más de 12 h
    frozen_clock.set(datetime(2026, 3, 29, 21, 0))
    assert run_scheduled.run(followup(outbox))["unconfirmed_alerts"] == 1
    frozen_clock.set(datetime(2026, 3, 29, 21, 10))
    assert run_scheduled.run(followup(outbox))["unconfirmed_alerts"] == 0  # uno solo

    [alert] = _alerts(outbox)
    assert alert["subject"] == "Sin confirmar: Lucía O'Connor, 30/03 09:00 h"
    assert "todavía no confirmó su turno" in alert["text"]
    assert "Lucía O'Connor" in alert["text"]
    assert PATIENT_EMAIL not in alert["text"]  # el aviso no lleva datos de contacto


def test_no_alert_once_the_patient_confirmed(client, db_session, make_professional, outbox, frozen_clock):  # noqa: F811
    _booked(client, db_session, make_professional)
    _remind(db_session, outbox, frozen_clock, datetime(2026, 3, 29, 9, 0))
    _confirm(client, _link_in(_to_patient(outbox)[-1]))
    outbox.sent.clear()

    frozen_clock.set(datetime(2026, 3, 29, 21, 0))

    assert run_scheduled.run(followup(outbox))["unconfirmed_alerts"] == 0
    assert _alerts(outbox) == []


def test_a_queued_alert_is_dropped_if_the_patient_confirms_first(client, db_session, make_professional, outbox, frozen_clock):  # noqa: F811
    appointment = _booked(client, db_session, make_professional)
    _remind(db_session, outbox, frozen_clock, datetime(2026, 3, 29, 9, 0))
    frozen_clock.set(datetime(2026, 3, 29, 21, 0))
    service = followup(outbox)
    assert service.prepare_unconfirmed_alerts(db_session) == 1
    _confirm(client, _link_in(_to_patient(outbox)[-1]))
    outbox.sent.clear()

    service.send_pending_notifications(db_session)

    assert _alerts(outbox) == []
    alert = db_session.scalars(
        select(Notification).where(Notification.type == NotificationType.PROFESSIONAL_PENDING)
    ).one()
    assert alert.error_message == "El paciente ya confirmó"
    assert _reload(db_session, appointment).status == AppointmentStatus.CONFIRMED


def test_no_alert_when_the_patient_was_asked_too_late(client, db_session, make_professional, outbox, frozen_clock):  # noqa: F811
    """Reservado a las 22 h para las 9 del día siguiente: a las 12 h todavía no se le había pedido nada."""
    frozen_clock.set(datetime(2026, 3, 29, 22, 0))
    _booked(client, db_session, make_professional)
    outbox.sent.clear()

    frozen_clock.set(datetime(2026, 3, 30, 0, 0))

    assert run_scheduled.run(followup(outbox))["unconfirmed_alerts"] == 0
    assert _alerts(outbox) == []


def test_an_already_confirmed_appointment_gets_a_plain_reminder(
    client, db_session, make_professional, outbox, frozen_clock, auth_headers  # noqa: F811
):
    appointment = _booked(client, db_session, make_professional)
    assert client.post(f"/api/v1/appointments/{appointment.id}/confirm", json={}, headers=auth_headers).status_code == 200

    _remind(db_session, outbox, frozen_clock, datetime(2026, 3, 29, 9, 0))

    reminder = _to_patient(outbox)[-1]
    assert reminder["subject"] == "Recordatorio de tu turno: 30/03 09:00 h"
    assert "/confirmar" not in reminder["text"]
    frozen_clock.set(datetime(2026, 3, 29, 21, 0))
    assert run_scheduled.run(followup(outbox))["unconfirmed_alerts"] == 0


def test_an_old_link_does_not_confirm_a_rescheduled_appointment(
    client, db_session, make_professional, outbox, frozen_clock, auth_headers  # noqa: F811
):
    appointment = _booked(client, db_session, make_professional)
    _remind(db_session, outbox, frozen_clock, datetime(2026, 3, 29, 9, 0))
    old_link = _link_in(_to_patient(outbox)[-1])

    moved = client.post(
        f"/api/v1/appointments/{appointment.id}/reschedule", json={"starts_at": "2026-03-30T11:00:00"}, headers=auth_headers
    )
    assert moved.status_code == 200, moved.text

    page = client.get(old_link)
    assert "Este link era para el horario anterior" in page.text
    assert "Sí, voy a ir" not in page.text
    assert "11:00" in page.text
    _confirm(client, old_link)
    assert _reload(db_session, appointment).status == AppointmentStatus.RESERVED


def test_a_reschedule_inside_24h_carries_a_new_link(
    client, db_session, make_professional, outbox, frozen_clock, auth_headers  # noqa: F811
):
    appointment = _booked(client, db_session, make_professional)
    _remind(db_session, outbox, frozen_clock, datetime(2026, 3, 29, 9, 0))
    old_link = _link_in(_to_patient(outbox)[-1])
    frozen_clock.set(datetime(2026, 3, 29, 12, 0))  # el lunes 11:00 queda a 23 h

    client.post(
        f"/api/v1/appointments/{appointment.id}/reschedule", json={"starts_at": "2026-03-30T11:00:00"}, headers=auth_headers
    )
    followup(outbox).send_pending_notifications(db_session)

    reschedule = _to_patient(outbox)[-1]
    assert reschedule["subject"].startswith("Cambiamos tu turno")
    new_link = _link_in(reschedule)
    assert new_link != old_link
    _confirm(client, new_link)
    assert _reload(db_session, appointment).status == AppointmentStatus.CONFIRMED
    assert _remind(db_session, outbox, frozen_clock, datetime(2026, 3, 29, 12, 10)) == 0  # no hace falta otro


def test_rescheduling_clears_the_confirmation(
    client, db_session, make_professional, outbox, frozen_clock, auth_headers  # noqa: F811
):
    appointment = _booked(client, db_session, make_professional)
    _remind(db_session, outbox, frozen_clock, datetime(2026, 3, 29, 9, 0))
    _confirm(client, _link_in(_to_patient(outbox)[-1]))
    assert _reload(db_session, appointment).status == AppointmentStatus.CONFIRMED

    client.post(
        f"/api/v1/appointments/{appointment.id}/reschedule", json={"starts_at": "2026-03-30T11:00:00"}, headers=auth_headers
    )

    appointment = _reload(db_session, appointment)
    assert appointment.status == AppointmentStatus.RESERVED
    assert appointment.attendance_confirmed_at is None
    assert appointment.confirmed_at is None


def test_a_moved_appointment_is_reminded_again(
    client, db_session, make_professional, outbox, frozen_clock, auth_headers  # noqa: F811
):
    """Antes, un turno ya recordado y movido a otra semana no se volvía a recordar."""
    appointment = _booked(client, db_session, make_professional, days=(date(2026, 3, 30), date(2026, 4, 6)))
    _remind(db_session, outbox, frozen_clock, datetime(2026, 3, 29, 9, 0))

    moved = client.post(
        f"/api/v1/appointments/{appointment.id}/reschedule", json={"starts_at": "2026-04-06T09:00:00"}, headers=auth_headers
    )
    assert moved.status_code == 200, moved.text

    assert _remind(db_session, outbox, frozen_clock, datetime(2026, 4, 5, 9, 0)) == 1
    reminder = _to_patient(outbox)[-1]
    assert reminder["subject"] == "Confirmá tu turno: 06/04 09:00 h"


def test_a_cancelled_appointment_cannot_be_confirmed(
    client, db_session, make_professional, outbox, frozen_clock, auth_headers  # noqa: F811
):
    appointment = _booked(client, db_session, make_professional)
    _remind(db_session, outbox, frozen_clock, datetime(2026, 3, 29, 9, 0))
    link = _link_in(_to_patient(outbox)[-1])
    client.post(f"/api/v1/appointments/{appointment.id}/cancel", json={}, headers=auth_headers)

    assert "Sí, voy a ir" not in client.get(link).text
    _confirm(client, link)

    assert _reload(db_session, appointment).status == AppointmentStatus.CANCELLED


def test_a_tampered_link_does_not_confirm(client, db_session, make_professional, outbox, frozen_clock):  # noqa: F811
    appointment = _booked(client, db_session, make_professional)

    page = client.get(f"/reservar/turno/{appointment.public_token}/confirmar?c=inventado")
    _confirm(client, f"/reservar/turno/{appointment.public_token}/confirmar?c=inventado")

    assert page.status_code == 200
    assert "Sí, voy a ir" not in page.text
    assert _reload(db_session, appointment).status == AppointmentStatus.RESERVED


def test_an_unconfirmed_appointment_is_never_cancelled(client, db_session, make_professional, outbox, frozen_clock):  # noqa: F811
    appointment = _booked(client, db_session, make_professional)

    for moment in (datetime(2026, 3, 29, 9, 0), datetime(2026, 3, 29, 21, 0), datetime(2026, 3, 30, 8, 50)):
        frozen_clock.set(moment)
        run_scheduled.run(followup(outbox))

    assert _reload(db_session, appointment).status == AppointmentStatus.RESERVED


def test_the_panel_says_the_patient_confirmed(client, db_session, make_professional, outbox, frozen_clock):  # noqa: F811
    from app.core.enums import UserRole
    from tests.conftest import create_user
    from tests.test_panel import login

    _booked(client, db_session, make_professional)
    _remind(db_session, outbox, frozen_clock, datetime(2026, 3, 29, 9, 0))
    _confirm(client, _link_in(_to_patient(outbox)[-1]))
    create_user(db_session, username="recepcion", role=UserRole.RECEPTIONIST)
    login(client, "recepcion")

    body = client.get("/app/appointments?selected_date=2026-03-30").text

    assert "✓ Confirmó el paciente" in body


def test_availability_fixture_is_monday_morning(db_session, make_professional):
    """Guarda contra cambios en el fixture: estos tests suponen el lunes 30/03 de 9 a 12."""
    professional_id = make_professional()
    window = db_session.scalars(select(AvailabilityWindow).where(AvailabilityWindow.professional_id == professional_id)).one()
    assert (window.availability_date, window.start_time) == (MONDAY_9.date(), time(9, 0))
