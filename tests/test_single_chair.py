"""Spec 0006: un solo sillón. Dos turnos nunca se superponen, aunque sean de profesionales distintos."""

from datetime import datetime, timedelta
from decimal import Decimal
from urllib.parse import unquote_plus

from sqlalchemy import select

from app.core.enums import AppointmentStatus, UserRole
from app.models.appointment import Appointment
from app.models.patient import Patient
from app.services.schedule_service import SLOT_TAKEN_MESSAGE
from tests.conftest import MONDAY, create_user
from tests.test_notifications import book, outbox  # noqa: F401  (fixture)
from tests.test_panel import login

NEXT_MONDAY = MONDAY + timedelta(days=7)


def _two_professionals(db_session, make_professional, days=(MONDAY,)):
    """Sabina y Nazarena atienden las dos el lunes de 9 a 12, con un solo sillón."""
    sabina = make_professional(name="Sabina", deposit=Decimal("0"), days=days)
    nazarena = make_professional(name="Nazarena", deposit=Decimal("0"), days=days)
    patient = Patient(dni="41333222", first_name="Tomás", last_name="Ruiz", email="tomas@example.com")
    db_session.add(patient)
    db_session.commit()
    create_user(db_session, username="admin", role=UserRole.ADMIN)
    return sabina, nazarena, patient.id


def _appointment(db_session, professional_id, *, at, minutes=30, status=AppointmentStatus.RESERVED, dni="30999888"):
    patient = db_session.scalar(select(Patient).where(Patient.dni == dni))
    if patient is None:
        patient = Patient(dni=dni, first_name="Lucía", last_name="Paz", email=f"{dni}@example.com")
        db_session.add(patient)
        db_session.flush()
    appointment = Appointment(
        patient_id=patient.id, professional_id=professional_id, starts_at=at, ends_at=at + timedelta(minutes=minutes),
        duration_minutes=minutes, status=status, created_by="test",
    )
    db_session.add(appointment)
    db_session.commit()
    return appointment


def _load_by_hand(client, professional_id, patient_id, *, at, minutes, day=MONDAY):
    return client.post(
        "/app/appointments",
        data={"patient_id": patient_id, "professional_id": professional_id, "manual_date": day.isoformat(),
              "manual_time": at, "duration_minutes": minutes},
        follow_redirects=False,
    )


def _flash(response) -> str:
    return unquote_plus(response.headers["location"])


def _online_slots(client, professional_id, day=MONDAY):
    response = client.get("/api/v1/availability/", params={"professional_id": professional_id, "date": day.isoformat()})
    assert response.status_code == 200, response.text
    return [slot["starts_at"][11:16] for slot in response.json()["slots"]]


def test_a_manual_appointment_cannot_overlap_another_professional(client, db_session, make_professional, outbox):  # noqa: F811
    sabina, nazarena, patient_id = _two_professionals(db_session, make_professional)
    _appointment(db_session, nazarena, at=datetime(2026, 3, 30, 11, 0))
    login(client, "admin")

    response = _load_by_hand(client, sabina, patient_id, at="10:30", minutes=60)

    assert (
        "Atención, el sillón está ocupado: Nazarena Gómez tiene un turno a las 11:00 (hasta 11:30). "
        "Acortá este turno para que termine a las 11:00 o elegí otro horario."
    ) in _flash(response)
    assert db_session.scalars(select(Appointment).where(Appointment.professional_id == sabina)).all() == []


def test_back_to_back_with_another_professional_is_fine(client, db_session, make_professional, outbox):  # noqa: F811
    sabina, nazarena, patient_id = _two_professionals(db_session, make_professional)
    _appointment(db_session, nazarena, at=datetime(2026, 3, 30, 11, 0))
    login(client, "admin")

    response = _load_by_hand(client, sabina, patient_id, at="10:00", minutes=60)

    assert "error=" not in response.headers["location"], _flash(response)


def test_online_slots_skip_the_chair_taken_by_another_professional(client, db_session, make_professional):
    sabina, nazarena, _ = _two_professionals(db_session, make_professional)
    _appointment(db_session, nazarena, at=datetime(2026, 3, 30, 10, 0), minutes=45)
    login(client, "admin")

    # 10:00 a 10:45 lo ocupa Nazarena: la grilla de Sabina arranca de nuevo a las 10:45.
    assert _online_slots(client, sabina) == ["09:00", "09:30", "10:45", "11:15"]


def test_an_online_patient_cannot_take_the_chair_from_another_professional(client, db_session, make_professional, outbox):  # noqa: F811
    sabina, nazarena, _ = _two_professionals(db_session, make_professional)
    _appointment(db_session, nazarena, at=datetime(2026, 3, 30, 11, 0))

    response = book(client, sabina, starts_at="2026-03-30T11:00:00")

    assert response.status_code == 422
    assert SLOT_TAKEN_MESSAGE in response.text
    # La página lista a las profesionales para elegir; lo que no puede aparecer es el detalle del otro turno.
    assert "sillón" not in response.text and "Nazarena Gómez tiene" not in response.text
    assert db_session.scalars(select(Appointment).where(Appointment.professional_id == sabina)).all() == []


def test_moving_onto_another_professional_is_rejected(client, db_session, make_professional, outbox):  # noqa: F811
    sabina, nazarena, _ = _two_professionals(db_session, make_professional)
    _appointment(db_session, nazarena, at=datetime(2026, 3, 30, 11, 0))
    mine = _appointment(db_session, sabina, at=datetime(2026, 3, 30, 9, 0), dni="30111000")
    login(client, "admin")

    response = client.post(
        f"/app/appointments/{mine.id}/edit",
        data={"edit_date": "2026-03-30", "edit_time": "11:15", "duration_minutes": "30", "status": "reserved"},
        follow_redirects=False,
    )

    assert "Atención, el sillón está ocupado: Nazarena Gómez tiene un turno de 11:00 a 11:30." in _flash(response)
    db_session.expire_all()
    assert db_session.get(Appointment, mine.id).starts_at == datetime(2026, 3, 30, 9, 0)


def test_reactivating_onto_another_professional_is_rejected(client, db_session, make_professional, outbox):  # noqa: F811
    sabina, nazarena, _ = _two_professionals(db_session, make_professional)
    cancelled = _appointment(db_session, sabina, at=datetime(2026, 3, 30, 11, 0), status=AppointmentStatus.CANCELLED)
    _appointment(db_session, nazarena, at=datetime(2026, 3, 30, 11, 0), dni="30111000")
    login(client, "admin")

    response = client.post(
        f"/app/appointments/{cancelled.id}/status", data={"action": "reserve", "return_to": "/app/appointments"},
        follow_redirects=False,
    )

    assert "el sillón está ocupado: Nazarena Gómez" in _flash(response)
    db_session.expire_all()
    assert db_session.get(Appointment, cancelled.id).status == AppointmentStatus.CANCELLED


def test_the_day_plan_shows_every_professional_in_the_chair(client, db_session, make_professional):
    sabina, nazarena, _ = _two_professionals(db_session, make_professional)
    _appointment(db_session, nazarena, at=datetime(2026, 3, 30, 11, 0))
    _appointment(db_session, sabina, at=datetime(2026, 3, 30, 9, 0), dni="30111000")
    login(client, "admin")

    response = client.get("/api/v1/availability/day-plan", params={"professional_id": sabina, "date": MONDAY.isoformat()})

    assert response.json()["busy"] == [
        {"start": "09:00", "end": "09:30", "professional_id": sabina, "professional": "Sabina Gómez"},
        {"start": "11:00", "end": "11:30", "professional_id": nazarena, "professional": "Nazarena Gómez"},
    ]


def test_a_cancelled_appointment_frees_the_chair(client, db_session, make_professional, outbox):  # noqa: F811
    sabina, nazarena, patient_id = _two_professionals(db_session, make_professional)
    _appointment(db_session, nazarena, at=datetime(2026, 3, 30, 11, 0), status=AppointmentStatus.CANCELLED)
    login(client, "admin")

    response = _load_by_hand(client, sabina, patient_id, at="11:00", minutes=30)

    assert "error=" not in response.headers["location"], _flash(response)


def test_a_series_skips_dates_when_the_chair_is_taken(client, db_session, make_professional, outbox):  # noqa: F811
    sabina, nazarena, patient_id = _two_professionals(db_session, make_professional, days=(MONDAY, NEXT_MONDAY))
    _appointment(db_session, nazarena, at=datetime(2026, 4, 6, 11, 0))
    login(client, "admin")

    response = client.post(
        "/app/appointments/series",
        data={"patient_id": patient_id, "professional_id": sabina, "series_date": MONDAY.isoformat(),
              "series_time": "11:00", "duration_minutes": "30", "every_weeks": "1", "occurrences": "2"},
        follow_redirects=False,
    )

    assert "No se pudieron cargar 1" in _flash(response)
    starts = [a.starts_at for a in db_session.scalars(select(Appointment).where(Appointment.professional_id == sabina))]
    assert starts == [datetime(2026, 3, 30, 11, 0)]
