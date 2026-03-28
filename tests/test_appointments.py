from sqlalchemy import select

from app.models.patient import Patient


def create_professional_with_availability(client, auth_headers, suffix: str = "1", phone: str | None = None):
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
    professional_id = professional_response.json()["id"]

    hours_response = client.post(
        "/api/v1/availability/windows",
        json={
            "professional_id": professional_id,
            "availability_date": "2026-03-30",
            "start_time": "09:00:00",
            "end_time": "13:00:00",
            "slot_duration_minutes": 30,
        },
        headers=auth_headers,
    )
    assert hours_response.status_code == 201
    return professional_id


def test_create_appointment_success(client, auth_headers):
    professional_id = create_professional_with_availability(client, auth_headers)

    response = client.post(
        "/api/v1/appointments/",
        json={
            "professional_id": professional_id,
            "patient": {
                "dni": "32123456",
                "first_name": "Mateo",
                "last_name": "Lopez",
                "email": "mateo@example.com",
                "phone": "+5491133333333",
                "observations": "Control semestral",
            },
            "starts_at": "2026-03-30T09:00:00",
            "duration_minutes": 30,
            "reason": "Limpieza",
        },
        headers=auth_headers,
    )

    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "reserved"
    assert data["patient"]["first_name"] == "Mateo"
    assert data["professional"]["first_name"] == "Laura"


def test_prevent_appointment_overlap(client, auth_headers):
    professional_id = create_professional_with_availability(client, auth_headers)

    first_response = client.post(
        "/api/v1/appointments/",
        json={
            "professional_id": professional_id,
            "patient": {
                "dni": "32123456",
                "first_name": "Mateo",
                "last_name": "Lopez",
                "email": "mateo@example.com",
                "phone": "+5491133333333",
                "observations": "Control",
            },
            "starts_at": "2026-03-30T10:00:00",
            "duration_minutes": 30,
            "reason": "Control",
        },
        headers=auth_headers,
    )
    assert first_response.status_code == 201

    overlap_response = client.post(
        "/api/v1/appointments/",
        json={
            "professional_id": professional_id,
            "patient": {
                "dni": "33444555",
                "first_name": "Sofia",
                "last_name": "Diaz",
                "email": "sofia@example.com",
                "phone": "+5491144444444",
                "observations": "Urgencia",
            },
            "starts_at": "2026-03-30T10:15:00",
            "duration_minutes": 30,
            "reason": "Urgencia",
        },
        headers=auth_headers,
    )

    assert overlap_response.status_code == 409
    assert "overlaps" in overlap_response.json()["detail"]


def test_patient_is_not_duplicated_when_booking_with_same_dni(client, auth_headers, db_session):
    professional_id = create_professional_with_availability(client, auth_headers)

    first_response = client.post(
        "/api/v1/appointments/",
        json={
            "professional_id": professional_id,
            "patient": {
                "dni": "30555111",
                "first_name": "Lucia",
                "last_name": "Fernandez",
                "email": "lucia@example.com",
                "phone": "+5491177777777",
                "observations": "Primera reserva",
            },
            "starts_at": "2026-03-30T11:00:00",
            "duration_minutes": 30,
            "reason": "Control",
        },
        headers=auth_headers,
    )
    assert first_response.status_code == 201

    second_response = client.post(
        "/api/v1/appointments/",
        json={
            "professional_id": professional_id,
            "patient": {
                "dni": "30555111",
                "first_name": "Lucia",
                "last_name": "Fernandez",
                "email": "lucia.updated@example.com",
                "phone": "+5491177777778",
                "observations": "Segunda reserva",
            },
            "starts_at": "2026-03-30T11:30:00",
            "duration_minutes": 30,
            "reason": "Seguimiento",
        },
        headers=auth_headers,
    )
    assert second_response.status_code == 201

    patients = db_session.scalars(select(Patient).where(Patient.dni == "30555111")).all()
    assert len(patients) == 1
    assert patients[0].email == "lucia.updated@example.com"


def test_prevent_patient_double_booking_in_same_time_range(client, auth_headers):
    professional_a = create_professional_with_availability(client, auth_headers, suffix="1", phone="+5491122222222")
    professional_b = create_professional_with_availability(client, auth_headers, suffix="2", phone="+5491122222233")

    first_response = client.post(
        "/api/v1/appointments/",
        json={
            "professional_id": professional_a,
            "patient": {
                "dni": "28444000",
                "first_name": "Nora",
                "last_name": "Vega",
                "email": "nora@example.com",
                "phone": "+5491166666666",
                "observations": "Primera consulta",
            },
            "starts_at": "2026-03-30T10:00:00",
            "duration_minutes": 30,
            "reason": "Control",
        },
        headers=auth_headers,
    )
    assert first_response.status_code == 201

    second_response = client.post(
        "/api/v1/appointments/",
        json={
            "professional_id": professional_b,
            "patient": {
                "dni": "28444000",
                "first_name": "Nora",
                "last_name": "Vega",
                "email": "nora@example.com",
                "phone": "+5491166666666",
                "observations": "Intento duplicado",
            },
            "starts_at": "2026-03-30T10:15:00",
            "duration_minutes": 30,
            "reason": "Segunda consulta",
        },
        headers=auth_headers,
    )

    assert second_response.status_code == 409
    assert "patient already has another appointment" in second_response.json()["detail"].lower()
