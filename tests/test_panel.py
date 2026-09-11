"""Internal panel: role permissions, professional scoping, users, availability tools and metrics."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.enums import AppointmentStatus, PaymentStatus, UserRole
from app.models.appointment import Appointment
from app.models.availability_window import AvailabilityWindow
from app.models.patient import Patient
from app.models.payment import Payment
from app.models.user import User
from tests.conftest import MONDAY, create_user


def login(client, username: str, password: str = "demo12345"):
    response = client.post("/app/login", data={"username": username, "password": password}, follow_redirects=False)
    assert response.status_code == 303, response.text
    return response


def add_appointment(db, professional_id: int, *, starts_at: datetime, status=AppointmentStatus.RESERVED, dni="30111222", **extra):
    patient = db.scalar(select(Patient).where(Patient.dni == dni))
    if patient is None:
        patient = Patient(dni=dni, first_name=f"Paciente{dni[-3:]}", last_name="Prueba", email=f"{dni}@example.com")
        db.add(patient)
        db.flush()
    appointment = Appointment(
        patient_id=patient.id,
        professional_id=professional_id,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=30),
        duration_minutes=30,
        status=status,
        created_by=extra.pop("created_by", "recepcion"),
        **extra,
    )
    db.add(appointment)
    db.commit()
    return appointment


@pytest.fixture()
def clinic(db_session, make_professional):
    laura = make_professional(name="Laura")
    pedro = make_professional(name="Pedro")
    create_user(db_session, username="admin", role=UserRole.ADMIN)
    create_user(db_session, username="recepcion", role=UserRole.RECEPTIONIST)
    create_user(db_session, username="laura", role=UserRole.PROFESSIONAL, professional_id=laura)
    return {"laura": laura, "pedro": pedro}


ADMIN_PAGES = [
    "/app",
    "/app/appointments",
    "/app/patients",
    "/app/professionals",
    "/app/availability",
    "/app/notifications",
    "/app/payments",
    "/app/payments?filter=refund",
    "/app/metrics",
    "/app/users",
]


def test_every_admin_page_renders(client, db_session, clinic):
    appointment = add_appointment(db_session, clinic["laura"], starts_at=datetime(2026, 3, 30, 9, 0))
    login(client, "admin")

    for path in [*ADMIN_PAGES, f"/app/appointments/{appointment.id}/edit", f"/app/patients/{appointment.patient_id}/edit", f"/app/professionals/{clinic['laura']}/edit", "/app/appointments?selected_date=2026-03-30"]:
        response = client.get(path)
        assert response.status_code == 200, (path, response.text[:500])
    assert client.get("/app/settings", follow_redirects=False).headers["location"] == "/app/availability"


@pytest.mark.parametrize("path", ["/app/professionals", "/app/users", "/app/metrics", "/app/payments", "/app/availability", "/app/notifications"])
def test_reception_cannot_open_admin_sections(client, clinic, path):
    login(client, "recepcion")

    response = client.get(path, follow_redirects=False)

    assert response.status_code in (302, 307)
    assert "permisos" in response.headers["location"]


def test_professional_only_sees_their_own_agenda(client, db_session, clinic):
    add_appointment(db_session, clinic["laura"], starts_at=datetime(2026, 3, 30, 9, 0), dni="30111222")
    add_appointment(db_session, clinic["pedro"], starts_at=datetime(2026, 3, 30, 10, 0), dni="30111333")
    login(client, "laura")

    dashboard = client.get("/app?selected_date=2026-03-30")
    agenda = client.get(f"/app/appointments?selected_date=2026-03-30&professional_id={clinic['pedro']}")

    for page in (dashboard, agenda):
        assert "Paciente222" in page.text
        assert "Paciente333" not in page.text
    assert "Mi agenda" in dashboard.text
    assert "Crear turno manual" not in agenda.text


def test_professional_cannot_open_patients_or_users(client, clinic):
    login(client, "laura")

    for path in ("/app/patients", "/app/users"):
        assert "permisos" in client.get(path, follow_redirects=False).headers["location"]


def test_professional_marks_own_appointments_but_cannot_cancel_or_touch_others(client, db_session, clinic, frozen_clock):
    own = add_appointment(db_session, clinic["laura"], starts_at=datetime(2026, 3, 30, 9, 0), status=AppointmentStatus.CONFIRMED)
    other = add_appointment(db_session, clinic["pedro"], starts_at=datetime(2026, 3, 30, 10, 0), dni="30111333")
    frozen_clock.set(datetime(2026, 3, 30, 12, 0))
    login(client, "laura")

    client.post(f"/app/appointments/{own.id}/status", data={"action": "complete"})
    cancel = client.post(f"/app/appointments/{own.id}/status", data={"action": "cancel"}, follow_redirects=False)
    foreign = client.post(f"/app/appointments/{other.id}/status", data={"action": "no_show"}, follow_redirects=False)

    db_session.expire_all()
    assert own.status == AppointmentStatus.COMPLETED
    assert "disponible" in cancel.headers["location"]
    assert other.status == AppointmentStatus.RESERVED
    assert "agenda" in foreign.headers["location"]


def test_professional_manages_only_their_availability(client, db_session, clinic):
    login(client, "laura")

    own = client.post(
        "/app/availability/windows",
        data={"professional_id": clinic["laura"], "availability_date": "2026-04-06", "start_time": "09:00", "end_time": "12:00", "slot_duration_minutes": "30"},
        follow_redirects=False,
    )
    foreign = client.post(
        "/app/availability/windows",
        data={"professional_id": clinic["pedro"], "availability_date": "2026-04-06", "start_time": "09:00", "end_time": "12:00", "slot_duration_minutes": "30"},
        follow_redirects=False,
    )

    assert "guardada" in own.headers["location"]
    assert "permisos" in foreign.headers["location"]
    owners = db_session.scalars(select(AvailabilityWindow.professional_id).where(AvailabilityWindow.availability_date == date(2026, 4, 6))).all()
    assert owners == [clinic["laura"]]


def test_unlinked_professional_sees_a_hint_instead_of_a_redirect_loop(client, db_session, clinic):
    create_user(db_session, username="nuevo", role=UserRole.PROFESSIONAL, professional_id=clinic["pedro"])
    user = db_session.scalar(select(User).where(User.username == "nuevo"))
    user.professional_id = None
    db_session.commit()
    login(client, "nuevo")

    response = client.get("/app")

    assert response.status_code == 200
    assert "no está vinculado" in response.text


# --------------------------------------------------------------------------- users


def test_admin_creates_a_professional_login(client, db_session, clinic):
    login(client, "admin")

    missing_link = client.post(
        "/app/users",
        data={"username": "pedro", "full_name": "Pedro Gómez", "email": "pedro@example.com", "password": "clave-segura", "role": "professional"},
        follow_redirects=False,
    )
    created = client.post(
        "/app/users",
        data={"username": "Pedro", "full_name": "Pedro Gómez", "email": "pedro@example.com", "password": "clave-segura", "role": "professional", "professional_id": str(clinic["pedro"])},
        follow_redirects=False,
    )
    duplicate_link = client.post(
        "/app/users",
        data={"username": "otro", "full_name": "Otro", "email": "otro@example.com", "password": "clave-segura", "role": "professional", "professional_id": str(clinic["laura"])},
        follow_redirects=False,
    )

    assert "vinculado" in missing_link.headers["location"]
    assert "Usuario+creado" in created.headers["location"]
    assert "ya+tiene+un+usuario" in duplicate_link.headers["location"]
    client.post("/app/logout")
    login(client, "pedro", "clave-segura")


def test_admin_cannot_lock_themselves_out(client, db_session, clinic):
    login(client, "admin")
    admin = db_session.scalar(select(User).where(User.username == "admin"))

    demote = client.post(f"/app/users/{admin.id}", data={"role": "receptionist", "is_active": "true"}, follow_redirects=False)

    assert "propio+rol" in demote.headers["location"]
    db_session.expire_all()
    assert admin.role == UserRole.ADMIN


def test_the_last_admin_cannot_be_removed(db_session, clinic):
    from app.core.config import get_settings
    from app.core.exceptions import DomainError
    from app.schemas.auth import UserUpdate
    from app.services.auth_service import AuthService

    service = AuthService(get_settings())
    admin = db_session.scalar(select(User).where(User.username == "admin"))
    other = create_user(db_session, username="admin2", role=UserRole.ADMIN)

    service.update_user(db_session, admin.id, UserUpdate(is_active=False), actor=other)
    with pytest.raises(DomainError, match="al menos un administrador"):
        service.update_user(db_session, other.id, UserUpdate(role=UserRole.RECEPTIONIST), actor=admin)


def test_password_reset(client, db_session, clinic):
    login(client, "admin")
    laura = db_session.scalar(select(User).where(User.username == "laura"))

    client.post(f"/app/users/{laura.id}/password", data={"password": "nueva-clave-1"})
    client.post("/app/logout")

    assert client.post("/app/login", data={"username": "laura", "password": "demo12345"}, follow_redirects=False).headers["location"].startswith("/app/login")
    login(client, "laura", "nueva-clave-1")


def test_login_is_rate_limited(client, clinic, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "login_rate_limit_per_15_minutes", 3)
    for _ in range(3):
        client.post("/app/login", data={"username": "admin", "password": "mala"})

    response = client.post("/app/login", data={"username": "admin", "password": "demo12345"}, follow_redirects=False)

    assert "Demasiados+intentos" in response.headers["location"]


# --------------------------------------------------------------------------- availability tools


def test_recurring_availability_skips_clashes_and_past_days(client, db_session, clinic):
    login(client, "admin")

    response = client.post(
        "/app/availability/recurring",
        data={
            "professional_id": clinic["pedro"],
            "date_from": "2026-03-23",
            "date_to": "2026-04-05",
            "weekdays": ["0", "2"],
            "start_time": "10:00",
            "end_time": "13:00",
            "slot_duration_minutes": "30",
        },
        follow_redirects=False,
    )

    assert "Se+cargaron+1+d%C3%ADa%28s%29.+Se+salte%C3%B3+3" in response.headers["location"]
    days = sorted(
        db_session.scalars(
            select(AvailabilityWindow.availability_date)
            .where(AvailabilityWindow.professional_id == clinic["pedro"])
            .where(AvailabilityWindow.start_time == time(10, 0))
        )
    )
    # 23 and 25 already passed (today is 27); the 30th clashes with the existing 9-12 block.
    assert days == [date(2026, 4, 1)]


def test_blocking_days_keeps_the_ones_with_appointments(client, db_session, clinic):
    for offset in (1, 2):
        db_session.add(
            AvailabilityWindow(
                professional_id=clinic["laura"],
                availability_date=MONDAY + timedelta(days=offset),
                start_time=time(9, 0),
                end_time=time(12, 0),
                slot_duration_minutes=30,
            )
        )
    db_session.commit()
    add_appointment(db_session, clinic["laura"], starts_at=datetime(2026, 3, 30, 9, 0))
    login(client, "admin")

    response = client.post(
        "/app/availability/clear",
        data={"professional_id": clinic["laura"], "date_from": "2026-03-30", "date_to": "2026-04-01"},
        follow_redirects=False,
    )

    assert "liberaron+2" in response.headers["location"]
    remaining = db_session.scalars(select(AvailabilityWindow.availability_date).where(AvailabilityWindow.professional_id == clinic["laura"])).all()
    assert remaining == [MONDAY]


# --------------------------------------------------------------------------- metrics


def test_clinic_metrics_definitions(db_session, clinic):
    from app.services.analytics import AnalyticsService

    laura = clinic["laura"]
    add_appointment(db_session, laura, starts_at=datetime(2026, 3, 30, 9, 0), status=AppointmentStatus.COMPLETED, dni="1000001")
    add_appointment(db_session, laura, starts_at=datetime(2026, 3, 30, 9, 30), status=AppointmentStatus.NO_SHOW, dni="1000002")
    paid = add_appointment(
        db_session, laura, starts_at=datetime(2026, 3, 30, 10, 0), status=AppointmentStatus.CONFIRMED, dni="1000003",
        deposit_amount=Decimal("10000"), created_by="public_booking",
    )
    add_appointment(
        db_session, laura, starts_at=datetime(2026, 3, 30, 10, 30), status=AppointmentStatus.EXPIRED, dni="1000004",
        deposit_amount=Decimal("10000"), created_by="public_booking",
    )
    add_appointment(db_session, laura, starts_at=datetime(2026, 3, 30, 11, 0), status=AppointmentStatus.CANCELLED, dni="1000005")
    db_session.add(
        Payment(
            appointment_id=paid.id, provider="mercadopago", status=PaymentStatus.APPROVED, amount=Decimal("10000"),
            currency="ARS", paid_at=datetime(2026, 3, 28, 12, 0),
        )
    )
    db_session.commit()

    stats = AnalyticsService().clinic_stats(db_session, date_from=date(2026, 3, 27), date_to=date(2026, 3, 31), professional_id=laura)

    assert stats.total == 4  # expired holds are not appointments
    assert stats.published_minutes == 180  # Laura's 9-12 window
    assert stats.booked_minutes == 90  # completed + no-show + confirmed
    assert stats.occupancy == 0.5
    assert stats.deposit_conversion == 0.5  # 1 paid of 2 deposit bookings
    assert stats.no_show_rate == 0.5
    assert stats.cancellation_rate == 0.25
    assert stats.deposits_collected == Decimal("10000")
    assert stats.online_share == pytest.approx(1 / 4)


def test_metrics_page_and_csv_export(client, db_session, clinic):
    add_appointment(db_session, clinic["laura"], starts_at=datetime(2026, 3, 30, 9, 0), status=AppointmentStatus.COMPLETED)
    login(client, "admin")

    page = client.get("/app/metrics?date_from=2026-03-27&date_to=2026-03-31")
    export = client.get("/app/metrics/export.csv?date_from=2026-03-27&date_to=2026-03-31")

    assert "Ocupación de la agenda" in page.text
    assert export.headers["content-type"].startswith("text/csv")
    lines = export.content.decode("utf-8-sig").splitlines()
    assert lines[0].startswith("fecha;hora;duracion_min;profesional")
    assert lines[1].startswith("2026-03-30;09:00;30;Laura Gómez;Paciente222 Prueba;30111222;Atendido;consultorio")
