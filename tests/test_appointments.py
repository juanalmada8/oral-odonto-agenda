from datetime import datetime, timedelta

from sqlalchemy import select, text

from app.core.enums import AppointmentStatus
from app.models.appointment import Appointment
from app.models.patient import Patient
from tests.conftest import MONDAY


def create_professional_with_availability(
    client,
    auth_headers,
    suffix: str = "1",
    phone: str | None = None,
    availability_date: str = "2026-03-30",
):
    professional_response = client.post(
        "/api/v1/professionals/",
        json={
            "first_name": "Laura",
            "last_name": "Gomez",
            "specialty": "Odontologia general",
            "email": f"laura{suffix}@example.com",
            "phone": phone or f"+54911222222{suffix}",
            "default_appointment_duration": 30,
        },
        headers=auth_headers,
    )
    assert professional_response.status_code == 201, professional_response.text
    professional_id = professional_response.json()["id"]

    hours_response = client.post(
        "/api/v1/availability/windows",
        json={
            "professional_id": professional_id,
            "availability_date": availability_date,
            "start_time": "09:00:00",
            "end_time": "13:00:00",
            "slot_duration_minutes": 30,
        },
        headers=auth_headers,
    )
    assert hours_response.status_code == 201, hours_response.text
    return professional_id


def book(client, auth_headers, professional_id, starts_at, dni="32123456", first_name="Mateo", last_name="Lopez"):
    return client.post(
        "/api/v1/appointments/",
        json={
            "professional_id": professional_id,
            "patient": {
                "dni": dni,
                "first_name": first_name,
                "last_name": last_name,
                "email": f"{first_name.lower()}@example.com",
                "phone": "+5491133333333",
            },
            "starts_at": starts_at,
            "duration_minutes": 30,
            "reason": "Control",
        },
        headers=auth_headers,
    )


def test_create_appointment_success(client, auth_headers):
    professional_id = create_professional_with_availability(client, auth_headers)

    response = book(client, auth_headers, professional_id, "2026-03-30T09:00:00")

    assert response.status_code == 201, response.text
    data = response.json()
    assert data["status"] == "reserved"
    assert data["patient"]["first_name"] == "Mateo"
    assert data["professional"]["first_name"] == "Laura"


def test_enum_values_are_persisted_not_member_names(client, auth_headers, db_session):
    professional_id = create_professional_with_availability(client, auth_headers)
    book(client, auth_headers, professional_id, "2026-03-30T09:00:00")

    stored_status = db_session.execute(text("SELECT status FROM appointment")).scalar_one()
    stored_role = db_session.execute(text('SELECT role FROM "user"')).scalar_one()

    assert stored_status == "reserved"
    assert stored_role == "admin"


def test_prevent_appointment_overlap(client, auth_headers):
    professional_id = create_professional_with_availability(client, auth_headers)
    assert book(client, auth_headers, professional_id, "2026-03-30T10:00:00").status_code == 201

    overlap_response = book(
        client, auth_headers, professional_id, "2026-03-30T10:15:00", dni="33444555", first_name="Sofia", last_name="Diaz"
    )

    assert overlap_response.status_code == 409
    # Al consultorio se le dice qué turno pisa (spec 0004); al paciente online, nunca.
    assert overlap_response.json()["detail"] == (
        "Atención, tenés un turno de 10:00 a 10:30. Empezá este turno a las 10:30 o elegí otro horario."
    )


def test_patient_is_not_duplicated_when_booking_with_same_dni(client, auth_headers, db_session):
    professional_id = create_professional_with_availability(client, auth_headers)
    assert book(client, auth_headers, professional_id, "2026-03-30T11:00:00", dni="30555111").status_code == 201
    assert book(client, auth_headers, professional_id, "2026-03-30T11:30:00", dni="30.555.111").status_code == 201

    patients = db_session.scalars(select(Patient).where(Patient.dni == "30555111")).all()
    assert len(patients) == 1


def test_prevent_patient_double_booking_in_same_time_range(client, auth_headers):
    professional_a = create_professional_with_availability(client, auth_headers, suffix="1", phone="+5491122222222")
    professional_b = create_professional_with_availability(client, auth_headers, suffix="2", phone="+5491122222233")
    assert book(client, auth_headers, professional_a, "2026-03-30T10:00:00", dni="28444000").status_code == 201

    second_response = book(client, auth_headers, professional_b, "2026-03-30T10:15:00", dni="28444000")

    assert second_response.status_code == 409
    assert "ya tiene otro turno" in second_response.json()["detail"]


def test_reject_appointments_in_the_past(client, auth_headers, frozen_clock):
    professional_id = create_professional_with_availability(client, auth_headers)
    frozen_clock.set(datetime(2026, 3, 30, 11, 0))

    response = book(client, auth_headers, professional_id, "2026-03-30T10:00:00")

    assert response.status_code == 422
    assert "ya pasaron" in response.json()["detail"]


def test_availability_hides_past_and_booked_slots(client, auth_headers, frozen_clock):
    professional_id = create_professional_with_availability(client, auth_headers)
    assert book(client, auth_headers, professional_id, "2026-03-30T12:00:00").status_code == 201
    frozen_clock.set(datetime(2026, 3, 30, 10, 40))

    response = client.get(
        "/api/v1/availability/",
        params={"professional_id": professional_id, "date": "2026-03-30"},
        headers=auth_headers,
    )

    starts = [slot["starts_at"][11:16] for slot in response.json()["slots"]]
    assert starts == ["11:00", "11:30", "12:30"]


def test_expired_payment_hold_releases_the_slot(client, auth_headers, db_session, frozen_clock):
    professional_id = create_professional_with_availability(client, auth_headers)
    patient = Patient(dni="40111222", first_name="Ana", last_name="Perez")
    db_session.add(patient)
    db_session.flush()
    hold = Appointment(
        patient_id=patient.id,
        professional_id=professional_id,
        starts_at=datetime(2026, 3, 30, 9, 0),
        ends_at=datetime(2026, 3, 30, 9, 30),
        duration_minutes=30,
        status=AppointmentStatus.PENDING_PAYMENT,
        hold_expires_at=frozen_clock.now() + timedelta(minutes=20),
        created_by="test",
    )
    db_session.add(hold)
    db_session.commit()

    assert book(client, auth_headers, professional_id, "2026-03-30T09:00:00").status_code == 409

    frozen_clock.advance(minutes=21)
    response = book(client, auth_headers, professional_id, "2026-03-30T09:00:00")

    assert response.status_code == 201, response.text
    db_session.refresh(hold)
    assert hold.status == AppointmentStatus.EXPIRED


def test_status_transitions_are_validated(client, auth_headers):
    professional_id = create_professional_with_availability(client, auth_headers)
    appointment_id = book(client, auth_headers, professional_id, "2026-03-30T09:00:00").json()["id"]

    completed = client.post(f"/api/v1/appointments/{appointment_id}/complete", json={}, headers=auth_headers)
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"

    cancel_completed = client.post(f"/api/v1/appointments/{appointment_id}/cancel", json={}, headers=auth_headers)
    assert cancel_completed.status_code == 409


def test_cancelled_appointment_can_be_reactivated_only_if_slot_is_free(client, auth_headers):
    professional_id = create_professional_with_availability(client, auth_headers)
    first_id = book(client, auth_headers, professional_id, "2026-03-30T09:00:00").json()["id"]
    assert client.post(f"/api/v1/appointments/{first_id}/cancel", json={}, headers=auth_headers).status_code == 200

    assert book(
        client, auth_headers, professional_id, "2026-03-30T09:00:00", dni="33444555", first_name="Sofia", last_name="Diaz"
    ).status_code == 201

    reactivate = client.put(f"/api/v1/appointments/{first_id}", json={"status": "reserved"}, headers=auth_headers)
    assert reactivate.status_code == 409


def test_cannot_delete_availability_with_active_appointments(client, auth_headers):
    professional_id = create_professional_with_availability(client, auth_headers)
    assert book(client, auth_headers, professional_id, "2026-03-30T09:00:00").status_code == 201
    window_id = client.get("/api/v1/availability/windows", headers=auth_headers).json()[0]["id"]

    response = client.delete(f"/api/v1/availability/windows/{window_id}", headers=auth_headers)

    assert response.status_code == 409
    assert "turno(s) activos" in response.json()["detail"]


def test_cannot_create_availability_in_the_past(client, auth_headers):
    professional_id = create_professional_with_availability(client, auth_headers)

    response = client.post(
        "/api/v1/availability/windows",
        json={
            "professional_id": professional_id,
            "availability_date": "2026-03-20",
            "start_time": "09:00:00",
            "end_time": "12:00:00",
        },
        headers=auth_headers,
    )

    assert response.status_code == 422


# ------------------------------------------------------------------ turnos largos cargados a mano


def _long_job_setup(db_session, make_professional, *, windows):
    """Profesional con bloques de disponibilidad a medida (lunes 30/03) y un paciente."""
    from datetime import time as time_of_day

    from app.models.availability_window import AvailabilityWindow
    from app.models.patient import Patient
    from app.models.professional import Professional

    professional_id = make_professional(days=())
    professional = db_session.get(Professional, professional_id)
    for start, end in windows:
        db_session.add(
            AvailabilityWindow(
                professional_id=professional.id, availability_date=MONDAY,
                start_time=time_of_day(*start), end_time=time_of_day(*end), slot_duration_minutes=30,
            )
        )
    patient = Patient(dni="41333222", first_name="Tomás", last_name="Ruiz", email="tomas@example.com")
    db_session.add(patient)
    db_session.commit()
    return professional_id, patient.id


def _horarios(client, auth_headers, professional_id, **extra):
    params = {"professional_id": professional_id, "date": MONDAY.isoformat(), **extra}
    respuesta = client.get("/api/v1/availability/", params=params, headers=auth_headers)
    assert respuesta.status_code == 200, respuesta.text
    return [(slot["starts_at"][11:16], slot["ends_at"][11:16]) for slot in respuesta.json()["slots"]]


def test_availability_can_be_asked_for_a_longer_appointment(client, db_session, make_professional, auth_headers):
    """Un trabajo de 2 h solo puede empezar donde entra entero: antes el formulario ofrecía bloques de 30 min."""
    professional_id, _ = _long_job_setup(db_session, make_professional, windows=[((9, 0), (12, 0))])

    assert _horarios(client, auth_headers, professional_id, duration_minutes=120) == [
        ("09:00", "11:00"), ("09:30", "11:30"), ("10:00", "12:00"),
    ]
    assert _horarios(client, auth_headers, professional_id)[0] == ("09:00", "09:30")  # sin duración, como siempre


def test_a_long_appointment_is_only_offered_where_it_does_not_collide(client, db_session, make_professional, auth_headers):
    from app.core.enums import AppointmentStatus
    from app.models.appointment import Appointment

    professional_id, patient_id = _long_job_setup(db_session, make_professional, windows=[((9, 0), (12, 0))])
    db_session.add(
        Appointment(
            patient_id=patient_id, professional_id=professional_id, starts_at=datetime(2026, 3, 30, 11, 30),
            ends_at=datetime(2026, 3, 30, 12, 0), duration_minutes=30, status=AppointmentStatus.RESERVED, created_by="test",
        )
    )
    db_session.commit()

    assert _horarios(client, auth_headers, professional_id, duration_minutes=120) == [("09:00", "11:00"), ("09:30", "11:30")]


def test_a_long_appointment_can_span_two_blocks_that_touch(client, db_session, make_professional, auth_headers):
    """La mañana cargada en dos pedazos (9 a 11 y 11 a 13) es, para el consultorio, una sola mañana."""
    professional_id, patient_id = _long_job_setup(db_session, make_professional, windows=[((9, 0), (11, 0)), ((11, 0), (13, 0))])

    assert ("10:00", "12:00") in _horarios(client, auth_headers, professional_id, duration_minutes=120)
    respuesta = client.post(
        "/api/v1/appointments/",
        json={"patient_id": patient_id, "professional_id": professional_id,
              "starts_at": "2026-03-30T10:00:00", "duration_minutes": 120},
        headers=auth_headers,
    )
    assert respuesta.status_code == 201, respuesta.text
    assert respuesta.json()["duration_minutes"] == 120


def test_a_long_appointment_cannot_cross_a_gap_in_the_availability(client, db_session, make_professional, auth_headers):
    professional_id, patient_id = _long_job_setup(db_session, make_professional, windows=[((9, 0), (11, 0)), ((12, 0), (14, 0))])

    assert ("10:00", "12:00") not in _horarios(client, auth_headers, professional_id, duration_minutes=120)
    respuesta = client.post(
        "/api/v1/appointments/",
        json={"patient_id": patient_id, "professional_id": professional_id,
              "starts_at": "2026-03-30T10:00:00", "duration_minutes": 120},
        headers=auth_headers,
    )
    assert respuesta.status_code == 409
    assert "disponibilidad" in respuesta.text


def test_a_long_manual_appointment_takes_every_slot_it_covers(client, db_session, make_professional, auth_headers):
    """Mientras dure el trabajo largo, el paciente que reserva online no ve esos horarios."""
    professional_id, patient_id = _long_job_setup(db_session, make_professional, windows=[((9, 0), (12, 0))])
    client.post(
        "/api/v1/appointments/",
        json={"patient_id": patient_id, "professional_id": professional_id,
              "starts_at": "2026-03-30T09:00:00", "duration_minutes": 120},
        headers=auth_headers,
    )

    assert _horarios(client, auth_headers, professional_id) == [("11:00", "11:30"), ("11:30", "12:00")]
