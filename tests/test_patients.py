from datetime import datetime, timedelta

import pytest

from app.core.enums import AppointmentStatus
from app.core.exceptions import DomainError
from app.models.appointment import Appointment
from app.models.patient import Patient
from app.models.professional import Professional
from app.services.reception_agent import ReceptionAgent


def test_create_patient(client, auth_headers):
    response = client.post(
        "/api/v1/patients/",
        json={
            "dni": "30123456",
            "first_name": "Ana",
            "last_name": "Perez",
            "email": "ana@example.com",
            "phone": "+5491111111111",
            "observations": "Paciente nueva",
        },
        headers=auth_headers,
    )

    assert response.status_code == 201
    data = response.json()
    assert data["dni"] == "30123456"
    assert data["first_name"] == "Ana"
    assert data["email"] == "ana@example.com"
    assert data["is_active"] is True


def test_delete_patient_blocks_when_has_active_appointments(db_session):
    reception_agent = ReceptionAgent()
    patient = Patient(dni="30000001", first_name="Ana", last_name="Perez", email="ana@test.com", is_active=True)
    professional = Professional(
        first_name="Laura",
        last_name="Gomez",
        specialty="General",
        email="laura.test@example.com",
        phone="+5491111111111",
        default_appointment_duration=30,
        is_active=True,
    )
    db_session.add_all([patient, professional])
    db_session.flush()

    starts_at = datetime(2026, 3, 30, 9, 0, 0)
    active_appointment = Appointment(
        patient_id=patient.id,
        professional_id=professional.id,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=30),
        duration_minutes=30,
        status=AppointmentStatus.RESERVED,
        reason="Control",
        created_by="test",
    )
    db_session.add(active_appointment)
    db_session.commit()

    with pytest.raises(DomainError) as exc:
        reception_agent.delete_patient(db_session, patient.id, actor="test")

    assert "turnos activos" in str(exc.value)


def test_delete_patient_allows_when_only_history_without_active(db_session):
    reception_agent = ReceptionAgent()
    patient = Patient(dni="30000002", first_name="Juan", last_name="Lopez", email="juan@test.com", is_active=True)
    professional = Professional(
        first_name="Martin",
        last_name="Suarez",
        specialty="Ortodoncia",
        email="martin.test@example.com",
        phone="+5491222222222",
        default_appointment_duration=30,
        is_active=True,
    )
    db_session.add_all([patient, professional])
    db_session.flush()

    starts_at = datetime(2026, 3, 30, 10, 0, 0)
    historical_appointment = Appointment(
        patient_id=patient.id,
        professional_id=professional.id,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=30),
        duration_minutes=30,
        status=AppointmentStatus.CANCELLED,
        reason="Control",
        created_by="test",
    )
    db_session.add(historical_appointment)
    db_session.commit()

    reception_agent.delete_patient(db_session, patient.id, actor="test")

    assert db_session.get(Patient, patient.id) is None
    assert db_session.get(Appointment, historical_appointment.id) is None
