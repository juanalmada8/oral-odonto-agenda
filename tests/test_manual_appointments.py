"""Spec 0004: turnos cargados a mano a cualquier hora, sin pisar nunca otro turno."""

from datetime import datetime, time, timedelta
from decimal import Decimal
from urllib.parse import unquote_plus

from sqlalchemy import select

from app.core.enums import AppointmentStatus, UserRole
from app.models.appointment import Appointment
from app.models.availability_window import AvailabilityWindow
from app.models.patient import Patient
from app.services.schedule_service import SLOT_TAKEN_MESSAGE
from tests.conftest import MONDAY, create_user
from tests.test_notifications import book, outbox  # noqa: F401  (fixture)
from tests.test_panel import login

PATIENT_EMAIL = "tomas@example.com"


def _clinic_with_a_40_minute_grid(db_session, make_professional):
    """El caso de Nazarena: grilla de 40 minutos para pacientes nuevos, de 9 a 13 el lunes 30/03."""
    professional_id = make_professional(days=(), deposit=Decimal("0"), name="Nazarena")
    db_session.add(
        AvailabilityWindow(
            professional_id=professional_id, availability_date=MONDAY,
            start_time=time(9, 0), end_time=time(13, 0), slot_duration_minutes=40,
        )
    )
    patient = Patient(dni="41333222", first_name="Tomás", last_name="Ruiz", email=PATIENT_EMAIL)
    db_session.add(patient)
    db_session.commit()
    create_user(db_session, username="admin", role=UserRole.ADMIN)
    return professional_id, patient.id


def _load_by_hand(client, professional_id, patient_id, *, at: str, minutes: int, day: str = MONDAY.isoformat()):
    return client.post(
        "/app/appointments",
        data={
            "patient_id": patient_id, "professional_id": professional_id,
            "manual_date": day, "manual_time": at, "duration_minutes": minutes,
        },
        follow_redirects=False,
    )


def _online_slots(client, professional_id):
    response = client.get("/api/v1/availability/", params={"professional_id": professional_id, "date": MONDAY.isoformat()})
    assert response.status_code == 200, response.text
    return [(slot["starts_at"][11:16], slot["ends_at"][11:16]) for slot in response.json()["slots"]]


def _booked_online(db_session, professional_id, *, at: datetime, minutes: int = 40) -> Appointment:
    patient = Patient(dni="30999888", first_name="Lucía", last_name="Paz", email="lucia@example.com")
    db_session.add(patient)
    db_session.flush()
    appointment = Appointment(
        patient_id=patient.id, professional_id=professional_id, starts_at=at,
        ends_at=at + timedelta(minutes=minutes),
        duration_minutes=minutes, status=AppointmentStatus.RESERVED, created_by="public_booking",
    )
    db_session.add(appointment)
    db_session.commit()
    return appointment


def _flash(response) -> str:
    return unquote_plus(response.headers["location"])


def test_a_manual_appointment_can_start_off_the_grid(client, db_session, make_professional, outbox):  # noqa: F811
    """Antes se cargaba a las 10:20 (la grilla) y después se editaba a las 10:00."""
    professional_id, patient_id = _clinic_with_a_40_minute_grid(db_session, make_professional)
    login(client, "admin")

    response = _load_by_hand(client, professional_id, patient_id, at="10:00", minutes=90)

    assert "error=" not in response.headers["location"], _flash(response)
    appointment = db_session.scalars(select(Appointment)).one()
    assert (appointment.starts_at, appointment.ends_at) == (datetime(2026, 3, 30, 10, 0), datetime(2026, 3, 30, 11, 30))
    assert appointment.status == AppointmentStatus.RESERVED


def test_a_manual_appointment_off_the_grid_sends_a_single_email(client, db_session, make_professional, outbox):  # noqa: F811
    professional_id, patient_id = _clinic_with_a_40_minute_grid(db_session, make_professional)
    login(client, "admin")

    _load_by_hand(client, professional_id, patient_id, at="10:00", minutes=90)

    to_patient = [message for message in outbox.sent if message["to"] == PATIENT_EMAIL]
    assert len(to_patient) == 1
    assert "10:00" in to_patient[0]["subject"]


def test_the_online_grid_restarts_after_a_manual_appointment(client, db_session, make_professional, outbox):  # noqa: F811
    """10:00 a 11:30 tapa 9:40, 10:20 y 11:00; el siguiente libre es 11:30, no 11:40."""
    professional_id, patient_id = _clinic_with_a_40_minute_grid(db_session, make_professional)
    login(client, "admin")
    assert _online_slots(client, professional_id)[:4] == [
        ("09:00", "09:40"), ("09:40", "10:20"), ("10:20", "11:00"), ("11:00", "11:40"),
    ]

    _load_by_hand(client, professional_id, patient_id, at="10:00", minutes=90)

    assert _online_slots(client, professional_id) == [("09:00", "09:40"), ("11:30", "12:10"), ("12:10", "12:50")]


def test_a_patient_can_book_the_slot_that_starts_where_a_manual_one_ends(client, db_session, make_professional, outbox):  # noqa: F811
    professional_id, patient_id = _clinic_with_a_40_minute_grid(db_session, make_professional)
    login(client, "admin")
    _load_by_hand(client, professional_id, patient_id, at="10:00", minutes=90)
    client.cookies.clear()

    response = book(client, professional_id, starts_at="2026-03-30T11:30:00")

    assert response.status_code == 303, response.text[:500]
    online = db_session.scalars(select(Appointment).where(Appointment.created_by == "public_booking")).one()
    assert (online.starts_at, online.ends_at) == (datetime(2026, 3, 30, 11, 30), datetime(2026, 3, 30, 12, 10))


def test_a_manual_appointment_that_overlaps_names_the_appointment_in_the_way(client, db_session, make_professional, outbox):  # noqa: F811
    professional_id, patient_id = _clinic_with_a_40_minute_grid(db_session, make_professional)
    _booked_online(db_session, professional_id, at=datetime(2026, 3, 30, 11, 0))
    login(client, "admin")

    response = _load_by_hand(client, professional_id, patient_id, at="10:00", minutes=90)

    assert (
        "Atención, tenés un turno a las 11:00 (hasta 11:40). "
        "Acortá este turno para que termine a las 11:00 o elegí otro horario."
    ) in _flash(response)
    assert len(db_session.scalars(select(Appointment)).all()) == 1


def test_a_manual_appointment_that_starts_inside_another_says_when_it_ends(client, db_session, make_professional, outbox):  # noqa: F811
    professional_id, patient_id = _clinic_with_a_40_minute_grid(db_session, make_professional)
    _booked_online(db_session, professional_id, at=datetime(2026, 3, 30, 9, 40))
    login(client, "admin")

    response = _load_by_hand(client, professional_id, patient_id, at="10:00", minutes=30)

    assert (
        "Atención, tenés un turno de 09:40 a 10:20. Empezá este turno a las 10:20 o elegí otro horario."
    ) in _flash(response)


def test_a_manual_appointment_shortened_to_end_where_the_next_starts_is_saved(client, db_session, make_professional, outbox):  # noqa: F811
    professional_id, patient_id = _clinic_with_a_40_minute_grid(db_session, make_professional)
    _booked_online(db_session, professional_id, at=datetime(2026, 3, 30, 11, 0))
    login(client, "admin")

    response = _load_by_hand(client, professional_id, patient_id, at="10:00", minutes=60)

    assert "error=" not in response.headers["location"], _flash(response)
    assert len(db_session.scalars(select(Appointment)).all()) == 2


def test_a_manual_appointment_can_go_outside_the_availability(client, db_session, make_professional, outbox):  # noqa: F811
    """La disponibilidad es lo que se ofrece online; la agenda la maneja el consultorio (sobreturnos, urgencias)."""
    professional_id, patient_id = _clinic_with_a_40_minute_grid(db_session, make_professional)
    login(client, "admin")

    past_closing = _load_by_hand(client, professional_id, patient_id, at="12:30", minutes=60)
    no_hours_that_day = _load_by_hand(client, professional_id, patient_id, at="17:15", minutes=45, day="2026-04-04")

    assert "error=" not in past_closing.headers["location"], _flash(past_closing)
    assert "error=" not in no_hours_that_day.headers["location"], _flash(no_hours_that_day)
    starts = sorted(a.starts_at for a in db_session.scalars(select(Appointment)))
    assert starts == [datetime(2026, 3, 30, 12, 30), datetime(2026, 4, 4, 17, 15)]


def test_moving_an_appointment_outside_the_availability_is_saved(client, db_session, make_professional, outbox):  # noqa: F811
    professional_id, patient_id = _clinic_with_a_40_minute_grid(db_session, make_professional)
    login(client, "admin")
    _load_by_hand(client, professional_id, patient_id, at="09:00", minutes=60)
    manual = db_session.scalars(select(Appointment)).one()

    response = client.post(
        f"/app/appointments/{manual.id}/edit",
        data={"edit_date": "2026-03-31", "edit_time": "18:30", "duration_minutes": "60", "status": "reserved"},
        follow_redirects=False,
    )

    assert "error=" not in response.headers["location"], _flash(response)
    db_session.expire_all()
    assert db_session.get(Appointment, manual.id).starts_at == datetime(2026, 3, 31, 18, 30)


def test_a_manual_appointment_in_the_past_is_rejected(client, db_session, make_professional, outbox):  # noqa: F811
    professional_id, patient_id = _clinic_with_a_40_minute_grid(db_session, make_professional)
    login(client, "admin")

    response = _load_by_hand(client, professional_id, patient_id, at="09:00", minutes=30, day="2026-03-27")

    assert "ya pasaron" in _flash(response)
    assert db_session.scalars(select(Appointment)).all() == []


def test_a_badly_written_time_is_rejected(client, db_session, make_professional, outbox):  # noqa: F811
    professional_id, patient_id = _clinic_with_a_40_minute_grid(db_session, make_professional)
    login(client, "admin")

    for written in ("25:00", "10.15", "diez", ""):
        response = _load_by_hand(client, professional_id, patient_id, at=written, minutes=30)
        assert "Escribí la hora en formato 24 h, por ejemplo 10:15." in _flash(response), written
    assert db_session.scalars(select(Appointment)).all() == []


def test_a_series_takes_date_and_24h_time(client, db_session, make_professional, outbox):  # noqa: F811
    professional_id, patient_id = _clinic_with_a_40_minute_grid(db_session, make_professional)
    login(client, "admin")

    response = client.post(
        "/app/appointments/series",
        data={
            "patient_id": patient_id, "professional_id": professional_id, "series_date": MONDAY.isoformat(),
            "series_time": "10:00", "duration_minutes": "40", "every_weeks": "4", "occurrences": "2",
        },
        follow_redirects=False,
    )

    # Solo el lunes 30/03 tiene atención: la segunda fecha se saltea, como siempre en una serie.
    assert "error=" not in response.headers["location"], _flash(response)
    assert [a.starts_at for a in db_session.scalars(select(Appointment))] == [datetime(2026, 3, 30, 10, 0)]


def test_an_online_patient_never_sees_who_has_the_slot(client, db_session, make_professional, outbox):  # noqa: F811
    professional_id, patient_id = _clinic_with_a_40_minute_grid(db_session, make_professional)
    login(client, "admin")
    _load_by_hand(client, professional_id, patient_id, at="10:00", minutes=90)
    client.cookies.clear()

    response = book(client, professional_id, starts_at="2026-03-30T10:20:00")

    assert response.status_code == 422
    assert "Atención" not in response.text
    assert SLOT_TAKEN_MESSAGE in response.text


def test_moving_an_appointment_onto_another_names_it(client, db_session, make_professional, outbox):  # noqa: F811
    professional_id, patient_id = _clinic_with_a_40_minute_grid(db_session, make_professional)
    _booked_online(db_session, professional_id, at=datetime(2026, 3, 30, 11, 0))
    login(client, "admin")
    _load_by_hand(client, professional_id, patient_id, at="09:00", minutes=60)
    manual = db_session.scalars(select(Appointment).where(Appointment.patient_id == patient_id)).one()

    response = client.post(
        f"/api/v1/appointments/{manual.id}/reschedule",
        json={"starts_at": "2026-03-30T10:30:00", "duration_minutes": 60},
    )

    assert response.status_code == 409
    assert response.json()["detail"].startswith("Atención, tenés un turno a las 11:00 (hasta 11:40).")


def test_the_manual_appointment_form_takes_any_start_time(client, db_session, make_professional):
    _clinic_with_a_40_minute_grid(db_session, make_professional)
    login(client, "admin")

    body = client.get("/app/appointments").text

    assert '<input type="date" name="manual_date" id="manual-date"' in body  # calendario, cualquier día
    assert 'name="manual_time" id="manual-time"' in body
    assert 'inputmode="numeric"' in body
    assert 'type="time"' not in body  # el selector con a.m./p.m. no aparece en ningún formulario
    assert 'type="datetime-local"' not in body
    assert 'id="manual-time-chips"' in body
    assert 'id="manual-next-days"' in body
    assert 'id="manual-starts-at"' not in body  # ya no hay lista de horarios de la grilla
    assert 'id="manual-day-plan"' in body


def test_the_day_plan_lists_availability_and_busy_times(client, db_session, make_professional):
    professional_id, _ = _clinic_with_a_40_minute_grid(db_session, make_professional)
    _booked_online(db_session, professional_id, at=datetime(2026, 3, 30, 11, 0))
    login(client, "admin")

    response = client.get("/api/v1/availability/day-plan", params={"professional_id": professional_id, "date": MONDAY.isoformat()})

    assert response.status_code == 200, response.text
    assert response.json() == {
        "professional_id": professional_id,
        "date": "2026-03-30",
        "spans": [{"start": "09:00", "end": "13:00"}],
        "busy": [{"start": "11:00", "end": "11:40", "professional_id": professional_id, "professional": "Nazarena Gómez"}],
    }


def test_the_day_plan_of_a_day_without_hours_is_empty(client, db_session, make_professional):
    professional_id, _ = _clinic_with_a_40_minute_grid(db_session, make_professional)
    login(client, "admin")

    response = client.get("/api/v1/availability/day-plan", params={"professional_id": professional_id, "date": "2026-04-04"})

    assert response.json()["spans"] == [] and response.json()["busy"] == []


def test_the_edit_form_uses_a_calendar_and_24h_time(client, db_session, make_professional, outbox):  # noqa: F811
    professional_id, patient_id = _clinic_with_a_40_minute_grid(db_session, make_professional)
    login(client, "admin")
    _load_by_hand(client, professional_id, patient_id, at="10:00", minutes=90)
    manual = db_session.scalars(select(Appointment)).one()

    body = client.get(f"/app/appointments/{manual.id}/edit").text

    assert 'type="date" name="edit_date"' in body and 'value="2026-03-30"' in body
    assert 'name="edit_time"' in body and 'value="10:00"' in body
    assert 'type="datetime-local"' not in body


def test_the_day_plan_is_for_staff_only(client, db_session, make_professional):
    professional_id, _ = _clinic_with_a_40_minute_grid(db_session, make_professional)

    response = client.get("/api/v1/availability/day-plan", params={"professional_id": professional_id, "date": MONDAY.isoformat()})

    assert response.status_code == 401
