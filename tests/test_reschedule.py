"""Spec 0008: el paciente ve solo la hora de inicio y puede reprogramar desde su link."""

import re
from datetime import datetime, timedelta

from sqlalchemy import select

from app.core.enums import AppointmentStatus
from app.models.appointment import Appointment
from tests.test_notifications import confirmed_booking, followup, notices, outbox  # noqa: F401  (fixture)
from tests.test_patient_confirmation import _booked, _link_in, _reload, _remind, _to_patient  # noqa: F401


def _reschedule_link(message: dict) -> str:
    links = re.findall(r"(/reservar/turno/[^/\s\"]+/reprogramar)", message["text"])
    assert links, message["text"]
    return links[0]


def test_the_patient_only_sees_the_start_time(client, db_session, make_professional, outbox, frozen_clock):  # noqa: F811
    appointment = _booked(client, db_session, make_professional)  # 09:00 a 09:30
    _remind(db_session, outbox, frozen_clock, datetime(2026, 3, 29, 9, 0))

    for message in _to_patient(outbox):
        assert "09:00 h" in message["text"] and "09:30" not in message["text"], message["subject"]
        assert "09:30" not in message["html"], message["subject"]
    page = client.get(f"/reservar/turno/{appointment.public_token}").text
    assert "09:00 h" in page and "09:30" not in page


def _put(client, auth_headers, appointment, **changes):
    response = client.put(f"/api/v1/appointments/{appointment.id}", json=changes, headers=auth_headers)
    assert response.status_code == 200, response.text


def test_changing_only_the_duration_does_not_notify_the_patient(
    client, db_session, make_professional, outbox, frozen_clock, auth_headers  # noqa: F811
):
    appointment = _booked(client, db_session, make_professional)
    _remind(db_session, outbox, frozen_clock, datetime(2026, 3, 29, 9, 0))
    client.post(_link_in(_to_patient(outbox)[-1]).split("?")[0], data={"c": _link_in(_to_patient(outbox)[-1]).split("c=")[1]})
    sent = len(_to_patient(outbox))

    _put(client, auth_headers, appointment, duration_minutes=60)

    appointment = _reload(db_session, appointment)
    assert appointment.ends_at == datetime(2026, 3, 30, 10, 0)
    assert appointment.status == AppointmentStatus.CONFIRMED
    assert appointment.attendance_confirmed_at is not None
    followup(outbox).send_pending_notifications(db_session)
    assert len(_to_patient(outbox)) == sent


def test_changing_only_the_duration_still_tells_the_professional(
    client, db_session, make_professional, outbox, auth_headers  # noqa: F811
):
    appointment = _booked(client, db_session, make_professional)
    outbox.sent.clear()

    _put(client, auth_headers, appointment, duration_minutes=60)
    followup(outbox).send_pending_notifications(db_session)

    assert _to_patient(outbox) == []
    [notice] = notices(outbox)
    assert "60 min" in notice["text"]
    assert "Antes:" not in notice["text"]


def test_changing_the_start_still_notifies_the_patient(
    client, db_session, make_professional, outbox, auth_headers  # noqa: F811
):
    appointment = _booked(client, db_session, make_professional)
    outbox.sent.clear()

    _put(client, auth_headers, appointment, starts_at="2026-03-30T10:00:00")
    followup(outbox).send_pending_notifications(db_session)

    [email] = _to_patient(outbox)
    assert email["subject"].startswith("Cambiamos tu turno")


def test_the_request_offers_choosing_another_time(client, db_session, make_professional, outbox, frozen_clock):  # noqa: F811
    appointment = _booked(client, db_session, make_professional)
    _remind(db_session, outbox, frozen_clock, datetime(2026, 3, 29, 9, 0))

    reminder = _to_patient(outbox)[-1]

    assert "Elegir otro horario" in reminder["html"]
    assert _reschedule_link(reminder) == f"/reservar/turno/{appointment.public_token}/reprogramar"


def test_the_reschedule_page_lists_free_slots(client, db_session, make_professional, outbox):  # noqa: F811
    appointment = _booked(client, db_session, make_professional)

    page = client.get(f"/reservar/turno/{appointment.public_token}/reprogramar")

    assert page.status_code == 200
    assert 'name="starts_at" value="2026-03-30T09:30:00"' in page.text
    assert 'value="2026-03-30T09:00:00"' not in page.text  # el suyo actual no se ofrece
    assert "09:30" in page.text and "09:30 a" not in page.text


def test_the_patient_reschedules_to_another_slot(client, db_session, make_professional, outbox, frozen_clock):  # noqa: F811
    appointment = _booked(client, db_session, make_professional)
    outbox.sent.clear()

    response = client.post(
        f"/reservar/turno/{appointment.public_token}/reprogramar",
        data={"starts_at": "2026-03-30T11:00:00"}, follow_redirects=False,
    )

    assert response.status_code == 303
    appointment = _reload(db_session, appointment)
    assert appointment.starts_at == datetime(2026, 3, 30, 11, 0)
    assert appointment.status == AppointmentStatus.CONFIRMED
    assert appointment.attendance_confirmed_at is not None
    assert len(db_session.scalars(select(Appointment)).all()) == 1
    [email] = _to_patient(outbox)
    assert email["subject"].startswith("Cambiamos tu turno")
    assert "Confirmar turno" not in email["html"]  # él mismo eligió: no hace falta confirmar de nuevo
    assert any(n["subject"].startswith("Turno movido") for n in notices(outbox))


def test_rescheduling_to_a_taken_slot_is_rejected(client, db_session, make_professional, outbox):  # noqa: F811
    appointment = _booked(client, db_session, make_professional)

    response = client.post(
        f"/reservar/turno/{appointment.public_token}/reprogramar",
        data={"starts_at": "2026-03-30T09:00:00"}, follow_redirects=False,
    )

    assert response.status_code in (200, 303, 422)
    assert _reload(db_session, appointment).starts_at == datetime(2026, 3, 30, 9, 0)
    assert "ya no está disponible" in client.get(response.headers["location"]).text if response.status_code == 303 else True


def test_rescheduling_with_deposit_respects_the_notice_period(client, db_session, make_professional, outbox, frozen_clock):  # noqa: F811
    appointment = confirmed_booking(client, db_session, make_professional)  # con seña, lunes 09:00
    frozen_clock.set(appointment.starts_at - timedelta(hours=5))

    page = client.get(f"/reservar/turno/{appointment.public_token}/reprogramar")
    client.post(
        f"/reservar/turno/{appointment.public_token}/reprogramar",
        data={"starts_at": "2026-03-30T11:00:00"}, follow_redirects=False,
    )

    assert "Faltan menos de 24 horas" in page.text
    assert 'name="starts_at"' not in page.text
    assert _reload(db_session, appointment).starts_at == datetime(2026, 3, 30, 9, 0)


def test_a_cancelled_appointment_cannot_be_rescheduled(client, db_session, make_professional, outbox, auth_headers):  # noqa: F811
    appointment = _booked(client, db_session, make_professional)
    client.post(f"/api/v1/appointments/{appointment.id}/cancel", json={}, headers=auth_headers)

    page = client.get(f"/reservar/turno/{appointment.public_token}/reprogramar")
    client.post(
        f"/reservar/turno/{appointment.public_token}/reprogramar",
        data={"starts_at": "2026-03-30T11:00:00"}, follow_redirects=False,
    )

    assert 'name="starts_at"' not in page.text
    assert _reload(db_session, appointment).status == AppointmentStatus.CANCELLED
