"""Spec 0009: buscador de pacientes con alta en el turno, y estados claros al editar."""

from datetime import datetime
from urllib.parse import unquote_plus

from sqlalchemy import select

from app.core.enums import AppointmentStatus, UserRole
from app.models.appointment import Appointment
from app.models.patient import Patient
from tests.conftest import MONDAY, create_user
from tests.test_notifications import outbox  # noqa: F401  (fixture)
from tests.test_panel import add_appointment, login


def _patients(db_session):
    db_session.add_all(
        [
            Patient(dni="30111222", first_name="María José", last_name="Pérez"),
            Patient(dni="30111333", first_name="Juan", last_name="Pérez"),
            Patient(dni="40999888", first_name="Tomás", last_name="Ruiz"),
            Patient(dni="40999777", first_name="Inés", last_name="Ruiz", is_active=False),
        ]
    )
    db_session.commit()
    create_user(db_session, username="admin", role=UserRole.ADMIN)


def _search(client, q):
    response = client.get("/api/v1/patients/search", params={"q": q})
    assert response.status_code == 200, response.text
    return response.json()


def test_patient_search_matches_name_surname_and_dni(client, db_session):
    _patients(db_session)
    login(client, "admin")

    assert [p["dni"] for p in _search(client, "tomas")] == ["40999888"]  # sin acento
    assert {p["dni"] for p in _search(client, "PEREZ")} == {"30111222", "30111333"}  # mayúsculas y acento
    assert [p["dni"] for p in _search(client, "maria jose")] == ["30111222"]
    assert [p["dni"] for p in _search(client, "30111333")] == ["30111333"]
    assert [p["dni"] for p in _search(client, "30.111.3")] == ["30111333"]  # DNI con puntos
    assert _search(client, "tomas")[0]["label"] == "Ruiz, Tomás"


def test_patient_search_limits_and_skips_inactive(client, db_session):
    _patients(db_session)
    for index in range(12):
        db_session.add(Patient(dni=f"5000{index:04d}", first_name="Lucía", last_name=f"Gómez{index}"))
    db_session.commit()
    login(client, "admin")

    assert _search(client, "a") == []  # menos de 2 caracteres
    assert len(_search(client, "gomez")) == 8
    assert _search(client, "ines") == []  # inactiva


def test_patient_search_is_for_staff_only(client, db_session):
    _patients(db_session)

    assert client.get("/api/v1/patients/search", params={"q": "ruiz"}).status_code == 401


def test_the_manual_form_uses_the_patient_search(client, db_session, make_professional):
    make_professional()
    _patients(db_session)
    login(client, "admin")

    body = client.get("/app/appointments").text

    assert body.count("data-patient-picker") >= 2  # turno manual y serie
    assert '<select name="patient_id"' not in body
    assert "patient-picker.js" in body
    assert 'name="new_dni"' in body and "Paciente nuevo" in body


def _manual(client, professional_id, **data):
    base = {
        "professional_id": professional_id, "manual_date": MONDAY.isoformat(), "manual_time": "10:00",
        "duration_minutes": 30,
    }
    return client.post("/app/appointments", data={**base, **data}, follow_redirects=False)


def _flash(response):
    return unquote_plus(response.headers["location"])


def test_a_new_patient_is_created_with_the_appointment(client, db_session, make_professional, outbox):  # noqa: F811
    professional_id = make_professional()
    _patients(db_session)
    login(client, "admin")

    response = _manual(
        client, professional_id, patient_id="", new_dni="31.222.444", new_first_name="rosa", new_last_name="de la fuente",
        new_phone="11 5555-4444", new_email="rosa@example.com",
    )

    assert "error=" not in response.headers["location"], _flash(response)
    patient = db_session.scalar(select(Patient).where(Patient.dni == "31222444"))
    assert (patient.first_name, patient.last_name) == ("Rosa", "De la Fuente")
    appointment = db_session.scalars(select(Appointment)).one()
    assert appointment.patient_id == patient.id


def test_a_new_patient_with_an_existing_dni_reuses_the_record(client, db_session, make_professional, outbox):  # noqa: F811
    professional_id = make_professional()
    _patients(db_session)
    login(client, "admin")

    _manual(client, professional_id, patient_id="", new_dni="40999888", new_first_name="Tomás", new_last_name="Ruiz")

    assert len(db_session.scalars(select(Patient).where(Patient.dni == "40999888")).all()) == 1
    assert db_session.scalars(select(Appointment)).one().patient.dni == "40999888"


def test_an_appointment_needs_a_patient(client, db_session, make_professional, outbox):  # noqa: F811
    professional_id = make_professional()
    _patients(db_session)
    login(client, "admin")

    response = _manual(client, professional_id, patient_id="")

    assert "Elegí un paciente o cargá uno nuevo." in _flash(response)
    assert db_session.scalars(select(Appointment)).all() == []


def test_a_new_patient_with_invalid_data_is_rejected(client, db_session, make_professional, outbox):  # noqa: F811
    professional_id = make_professional()
    _patients(db_session)
    login(client, "admin")

    response = _manual(client, professional_id, patient_id="", new_dni="123", new_first_name="R2", new_last_name="Paz")

    assert "error=" in response.headers["location"]
    assert db_session.scalars(select(Appointment)).all() == []
    assert db_session.scalar(select(Patient).where(Patient.last_name == "Paz")) is None


def test_the_edit_form_only_offers_possible_statuses(client, db_session, make_professional):
    professional_id = make_professional()
    _patients(db_session)
    appointment = add_appointment(db_session, professional_id, starts_at=datetime(2026, 3, 30, 9, 0))
    login(client, "admin")

    body = client.get(f"/app/appointments/{appointment.id}/edit").text

    for value, label in (
        ("reserved", "Reservado (sin cambios)"), ("confirmed", "Confirmado"), ("completed", "Atendido"),
        ("no_show", "Ausente"), ("cancelled", "Cancelar el turno (se le avisa al paciente)"),
    ):
        assert f'<option value="{value}"' in body and f">{label}</option>" in body, label
    assert "Vencido" not in body and "Pendiente de pago" not in body
    assert 'value="expired"' not in body and 'value="pending_payment"' not in body


def test_a_cancelled_appointment_offers_reactivate(client, db_session, make_professional):
    professional_id = make_professional()
    _patients(db_session)
    appointment = add_appointment(
        db_session, professional_id, starts_at=datetime(2026, 3, 30, 9, 0), status=AppointmentStatus.CANCELLED
    )
    login(client, "admin")

    body = client.get(f"/app/appointments/{appointment.id}/edit").text

    assert "Reactivar el turno" in body
    assert 'value="reserved"' in body
