"""Spec 0011: el panel dice quién creó cada turno."""

from datetime import datetime

import pytest

from app.core.enums import UserRole
from tests.conftest import create_user
from tests.test_panel import add_appointment, login

DAY = "/app/appointments?selected_date=2026-03-30"
WHEN = datetime(2026, 3, 30, 9, 0)


@pytest.fixture()
def clinic(db_session, make_professional):
    laura = make_professional(name="Laura")
    create_user(db_session, username="admin", role=UserRole.ADMIN)
    create_user(db_session, username="recepcion", role=UserRole.RECEPTIONIST)
    create_user(db_session, username="laura", role=UserRole.PROFESSIONAL, professional_id=laura)
    return {"laura": laura}


def test_online_booking_says_the_patient_booked_it(client, db_session, clinic):
    add_appointment(db_session, clinic["laura"], starts_at=WHEN, created_by="public_booking")
    login(client, "admin")

    page = client.get(DAY).text

    assert "Reservó el paciente" in page
    assert "Cargó" not in page


def test_manual_appointment_names_who_loaded_it(client, db_session, clinic):
    add_appointment(db_session, clinic["laura"], starts_at=WHEN, created_by="recepcion")
    login(client, "admin")

    page = client.get(DAY).text

    assert "Cargó Recepcion Test (recepción)" in page
    assert "Reservó el paciente" not in page


def test_a_professional_who_loaded_an_appointment_is_named(client, db_session, clinic):
    add_appointment(db_session, clinic["laura"], starts_at=WHEN, created_by="laura")
    login(client, "laura")

    page = client.get(DAY).text

    assert "Cargó Laura Test (profesional)" in page


def test_unknown_creator_falls_back_to_the_clinic(client, db_session, clinic):
    add_appointment(db_session, clinic["laura"], starts_at=WHEN, created_by="seed_demo", dni="30111222")
    add_appointment(db_session, clinic["laura"], starts_at=datetime(2026, 3, 30, 10, 0), created_by="se_fue", dni="30111333")
    login(client, "admin")

    page = client.get(DAY).text

    assert page.count("Cargado en el consultorio") == 2
    assert "seed_demo" not in page
    assert "se_fue" not in page


def test_dashboard_agenda_shows_the_origin(client, db_session, clinic):
    add_appointment(db_session, clinic["laura"], starts_at=WHEN, created_by="public_booking")
    login(client, "admin")

    page = client.get("/app?selected_date=2026-03-30").text

    assert "Reservó el paciente" in page


def test_patient_pages_do_not_show_the_origin(client, db_session, clinic):
    appointment = add_appointment(db_session, clinic["laura"], starts_at=WHEN, created_by="recepcion")

    response = client.get(f"/reservar/turno/{appointment.public_token}")

    assert response.status_code == 200
    page = response.text
    assert "Cargó" not in page
    assert "Reservó el paciente" not in page


def test_origin_name_is_escaped(client, db_session, clinic):
    user = create_user(db_session, username="xss", role=UserRole.RECEPTIONIST)
    user.full_name = "<b>Ana</b>"
    db_session.commit()
    add_appointment(db_session, clinic["laura"], starts_at=WHEN, created_by="xss")
    login(client, "admin")

    page = client.get(DAY).text

    assert "<b>Ana</b>" not in page
    assert "&lt;b&gt;Ana&lt;/b&gt;" in page
