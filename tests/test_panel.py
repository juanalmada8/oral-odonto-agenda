"""Internal panel: role permissions, professional scoping, users, availability tools and metrics."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from urllib.parse import unquote_plus

import pytest
from sqlalchemy import select

from app.core.enums import AppointmentStatus, PaymentStatus, UserRole
from app.models.appointment import Appointment
from app.models.availability_window import AvailabilityWindow
from app.models.patient import Patient
from app.models.payment import Payment
from app.models.professional import Professional
from app.models.user import User
from app.services.analytics import AnalyticsService
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

    assert response.status_code == 303
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


def test_csv_export_neutralizes_spreadsheet_formulas(client, db_session, clinic):
    """The "motivo" is typed by the patient on the public site and lands in a file staff open in Excel."""
    add_appointment(
        db_session,
        clinic["laura"],
        starts_at=datetime(2026, 3, 30, 9, 0),
        reason='=HYPERLINK("http://evil.example","cobrar")',
    )
    login(client, "admin")

    export = client.get("/app/metrics/export.csv?date_from=2026-03-27&date_to=2026-03-31")

    assert "'=HYPERLINK" in export.text
    assert ";=HYPERLINK" not in export.text


def _approved_deposit(db, professional_id: int, *, status=AppointmentStatus.CANCELLED, dni="4100001") -> Payment:
    appointment = add_appointment(db, professional_id, starts_at=datetime(2026, 3, 30, 15, 0), status=status, dni=dni)
    payment = Payment(
        appointment_id=appointment.id, provider="mercadopago", status=PaymentStatus.APPROVED,
        amount=Decimal("10000"), currency="ARS", paid_at=datetime(2026, 3, 28, 12, 0),
    )
    db.add(payment)
    db.commit()
    return payment


def test_deposit_of_a_cancelled_appointment_can_be_marked_refunded_by_hand(client, db_session, clinic):
    """Refunds paid outside Mercado Pago (transfer, cash) have to leave a record."""
    payment = _approved_deposit(db_session, clinic["laura"])
    login(client, "admin")
    assert "Marcar devuelta" in client.get("/app/payments?filter=refund").text

    client.post(f"/app/payments/{payment.id}/refund", data={"return_to": "/app/payments"}, follow_redirects=False)

    db_session.expire_all()
    assert db_session.get(Payment, payment.id).status == PaymentStatus.REFUNDED
    # Once refunded it stops being pending, so the panel no longer nags about it.
    assert "Marcar devuelta" not in client.get("/app/payments?filter=refund").text


def test_deposit_of_a_live_appointment_cannot_be_marked_refunded(client, db_session, clinic):
    payment = _approved_deposit(db_session, clinic["laura"], status=AppointmentStatus.CONFIRMED)
    login(client, "admin")

    client.post(f"/app/payments/{payment.id}/refund", follow_redirects=False)

    db_session.expire_all()
    assert db_session.get(Payment, payment.id).status == PaymentStatus.APPROVED


def test_reception_cannot_mark_a_deposit_refunded(client, db_session, clinic):
    payment = _approved_deposit(db_session, clinic["laura"])
    login(client, "recepcion")

    response = client.post(f"/app/payments/{payment.id}/refund", follow_redirects=False)

    # 303 and not 307: the browser must not replay the POST against the redirect target.
    assert response.status_code == 303
    db_session.expire_all()
    assert db_session.get(Payment, payment.id).status == PaymentStatus.APPROVED


def test_manual_appointment_can_record_a_cash_deposit(client, db_session, clinic):
    """At the desk the deposit is often paid in cash; it has to count like an online one."""
    patient = Patient(dni="41222333", first_name="Rocio", last_name="Paz", email="rocio@example.com")
    db_session.add(patient)
    db_session.commit()
    login(client, "admin")

    client.post(
        "/app/appointments",
        data={
            "patient_id": patient.id, "professional_id": clinic["laura"],
            "starts_at": "2026-03-30T09:00", "duration_minutes": 30,
            "reason": "Control", "cash_deposit": "10.000",
        },
        follow_redirects=False,
    )

    appointment = db_session.scalars(select(Appointment).where(Appointment.patient_id == patient.id)).one()
    assert appointment.status == AppointmentStatus.CONFIRMED
    assert appointment.deposit_amount == Decimal("10000")
    payment = db_session.scalars(select(Payment).where(Payment.appointment_id == appointment.id)).one()
    assert (payment.provider, payment.status) == ("efectivo", PaymentStatus.APPROVED)


def test_manual_appointment_without_deposit_stays_reserved(client, db_session, clinic):
    patient = Patient(dni="41222444", first_name="Nico", last_name="Paz", email="nico@example.com")
    db_session.add(patient)
    db_session.commit()
    login(client, "admin")

    client.post(
        "/app/appointments",
        data={
            "patient_id": patient.id, "professional_id": clinic["laura"],
            "starts_at": "2026-03-30T10:00", "duration_minutes": 30, "cash_deposit": "",
        },
        follow_redirects=False,
    )

    appointment = db_session.scalars(select(Appointment).where(Appointment.patient_id == patient.id)).one()
    assert appointment.status == AppointmentStatus.RESERVED
    assert db_session.scalars(select(Payment).where(Payment.appointment_id == appointment.id)).all() == []


def test_la_ficha_no_guarda_informacion_clinica(client, db_session, clinic):
    """El sistema es una agenda: con datos de salud la base pasa a ser de datos sensibles."""
    login(client, "admin")
    paciente = Patient(dni="41999111", first_name="Vera", last_name="Luna")
    db_session.add(paciente)
    db_session.commit()

    ficha = client.get(f"/app/patients/{paciente.id}/edit").text

    assert "medical_notes" not in ficha
    assert "Antecedentes" not in ficha
    assert not hasattr(Patient, "medical_notes")


def test_patient_record_fields_are_saved_by_hand(client, db_session, clinic):
    """Address, birth date and insurance are typed at the desk: online booking never asks for them."""
    patient = Patient(dni="41555666", first_name="Vera", last_name="Luna", email="vera@example.com")
    db_session.add(patient)
    db_session.commit()
    login(client, "admin")

    client.post(
        f"/app/patients/{patient.id}/edit",
        data={
            "dni": "41555666", "first_name": "Vera", "last_name": "Luna",
            "email": "vera@example.com", "phone": "", "observations": "", "is_active": "true",
            "birth_date": "1990-07-15", "address": "Soloeta 443", "city": "General Belgrano",
            "health_insurance": "IOMA", "health_insurance_number": "12345/6",
            "emergency_contact": "Juan Luna 2241-556677",
        },
        follow_redirects=False,
    )

    db_session.expire_all()
    saved = db_session.get(Patient, patient.id)
    assert saved.birth_date == date(1990, 7, 15)
    assert saved.address == "Soloeta 443"
    assert saved.health_insurance_number == "12345/6"


def test_editing_a_professional_deposit_does_not_break_the_audit_log(client, db_session, clinic):
    """The audit column is JSON: a Decimal (or a date) has to be stored as text, not as the object."""
    login(client, "admin")

    response = client.post(
        f"/app/professionals/{clinic['laura']}/edit",
        data={
            "first_name": "Laura", "last_name": "Gómez", "specialty": "Odontología general",
            "email": "laura@example.com", "phone": "", "default_appointment_duration": "30",
            "deposit_amount": "12500", "is_active": "true",
        },
        follow_redirects=False,
    )

    assert "error" not in response.headers["location"]
    db_session.expire_all()
    assert db_session.get(Professional, clinic["laura"]).deposit_amount == Decimal("12500")


def test_row_shows_only_the_next_step_and_hides_the_rest_in_a_menu(client, db_session, clinic):
    """Five buttons per row were unreadable: the expected action stays out, the rest go behind ⋯."""
    add_appointment(db_session, clinic["laura"], starts_at=datetime(2026, 3, 30, 9, 0), status=AppointmentStatus.RESERVED)
    login(client, "admin")

    page = client.get("/app/appointments?selected_date=2026-03-30").text

    assert page.count('class="primary-button compact ') == 1
    assert "Confirmar" in page
    assert 'class="row-menu"' in page


def test_a_finished_appointment_offers_no_primary_action(client, db_session, clinic, frozen_clock):
    """Nothing "comes next" after Atendido: what is left are corrections, and those live in the menu."""
    add_appointment(db_session, clinic["laura"], starts_at=datetime(2026, 3, 30, 9, 0), status=AppointmentStatus.COMPLETED)
    login(client, "admin")

    page = client.get("/app/appointments?selected_date=2026-03-30").text

    assert 'class="primary-button' not in page
    assert 'class="row-menu"' in page


def test_what_the_visit_was_charged_feeds_the_revenue_metric(client, db_session, clinic):
    """The deposit is an advance, not the price: revenue counted only deposits before this."""
    appointment = add_appointment(
        db_session, clinic["laura"], starts_at=datetime(2026, 3, 30, 9, 0),
        status=AppointmentStatus.COMPLETED, deposit_amount=Decimal("10000"),
    )
    login(client, "admin")

    client.post(
        f"/app/appointments/{appointment.id}/edit",
        data={
            "starts_at": "2026-03-30T09:00", "duration_minutes": "30", "status": "completed",
            "reason": "Limpieza", "notes": "", "charged_amount": "40.000",
        },
        follow_redirects=False,
    )

    db_session.expire_all()
    assert db_session.get(Appointment, appointment.id).charged_amount == Decimal("40000")
    stats = AnalyticsService().clinic_stats(db_session, date_from=date(2026, 3, 27), date_to=date(2026, 3, 31))
    assert stats.charged_total == Decimal("40000")
    assert stats.charged_appointments == 1
    assert stats.attended_without_charge == 0


def test_an_attended_visit_with_no_charge_loaded_is_flagged(client, db_session, clinic):
    add_appointment(db_session, clinic["laura"], starts_at=datetime(2026, 3, 30, 9, 0), status=AppointmentStatus.COMPLETED)

    stats = AnalyticsService().clinic_stats(db_session, date_from=date(2026, 3, 27), date_to=date(2026, 3, 31))

    assert (stats.charged_total, stats.attended_without_charge) == (Decimal("0"), 1)


def _publish_mornings(db, professional_id: int, days: list[date]) -> None:
    for day in days:
        db.add(
            AvailabilityWindow(
                professional_id=professional_id, availability_date=day,
                start_time=time(9, 0), end_time=time(12, 0), slot_duration_minutes=30,
            )
        )
    db.commit()


def test_a_treatment_series_loads_every_appointment_at_once(client, db_session, clinic):
    """Ortodoncia es control mensual por meses: cargarlos de a uno es inviable."""
    patient = Patient(dni="41777888", first_name="Tomás", last_name="Ruiz", email="tomas@example.com")
    db_session.add(patient)
    _publish_mornings(db_session, clinic["laura"], [date(2026, 4, 27), date(2026, 5, 25)])
    db_session.commit()
    login(client, "admin")

    client.post(
        "/app/appointments/series",
        data={
            "patient_id": patient.id, "professional_id": clinic["laura"],
            "starts_at": "2026-03-30T09:00", "duration_minutes": "30",
            "every_weeks": "4", "occurrences": "3", "reason": "Control de ortodoncia",
        },
        follow_redirects=False,
    )

    appointments = db_session.scalars(
        select(Appointment).where(Appointment.patient_id == patient.id).order_by(Appointment.starts_at)
    ).all()
    assert [a.starts_at for a in appointments] == [
        datetime(2026, 3, 30, 9, 0), datetime(2026, 4, 27, 9, 0), datetime(2026, 5, 25, 9, 0)
    ]
    assert {a.status for a in appointments} == {AppointmentStatus.RESERVED}


def test_a_series_skips_taken_dates_instead_of_failing(client, db_session, clinic):
    """Sobre un año de controles alguna fecha siempre va a estar ocupada."""
    patient = Patient(dni="41777999", first_name="Ana", last_name="Ruiz", email="ana2@example.com")
    db_session.add(patient)
    db_session.commit()
    _publish_mornings(db_session, clinic["laura"], [date(2026, 4, 27), date(2026, 5, 25)])
    # El segundo turno de la serie cae sobre uno que ya existe.
    add_appointment(db_session, clinic["laura"], starts_at=datetime(2026, 4, 27, 9, 0), dni="30111222")
    login(client, "admin")

    response = client.post(
        "/app/appointments/series",
        data={
            "patient_id": patient.id, "professional_id": clinic["laura"],
            "starts_at": "2026-03-30T09:00", "every_weeks": "4", "occurrences": "3",
        },
        follow_redirects=False,
    )

    created = db_session.scalars(select(Appointment).where(Appointment.patient_id == patient.id)).all()
    assert len(created) == 2
    assert "No se pudieron cargar 1" in unquote_plus(response.headers["location"])


def test_the_agenda_does_not_query_more_as_appointments_grow(client, db_session, clinic):
    """El badge de seña lee latest_payment: sin eager loading la agenda hacía una consulta por fila."""
    from sqlalchemy import event

    from app.db.session import engine

    for minuto in range(0, 60, 30):
        add_appointment(db_session, clinic["laura"], starts_at=datetime(2026, 3, 30, 9, minuto), dni=f"3011{minuto:04d}")
    login(client, "admin")

    consultas: list[str] = []

    def registrar(conn, cursor, statement, params, context, executemany):
        consultas.append(statement)

    event.listen(engine, "before_cursor_execute", registrar)
    try:
        client.get("/app/appointments?selected_date=2026-03-30")
        con_dos = len(consultas)
        # Uno detrás del otro: superpuestos, PostgreSQL los rechaza por la restricción de exclusión.
        for indice in range(12):
            add_appointment(
                db_session, clinic["laura"],
                starts_at=datetime(2026, 3, 30, 11, 0) + timedelta(minutes=30 * indice),
                dni=f"3022{indice:04d}",
            )
        consultas.clear()
        client.get("/app/appointments?selected_date=2026-03-30")
        con_muchos = len(consultas)
    finally:
        event.remove(engine, "before_cursor_execute", registrar)

    # No tiene que crecer con la cantidad de filas; que baje alguna es indistinto.
    assert con_muchos <= con_dos, f"la agenda escala con la cantidad de turnos: {con_dos} -> {con_muchos}"


# --------------------------------------------------------------- alta del primer admin


def _run_create_admin(monkeypatch, **variables):
    from app.tasks import create_admin

    for nombre in ("ADMIN_USERNAME", "ADMIN_PASSWORD", "ADMIN_FULL_NAME", "ADMIN_EMAIL"):
        monkeypatch.delenv(nombre, raising=False)
    for nombre, valor in variables.items():
        monkeypatch.setenv(nombre, valor)
    return create_admin.main()


def test_create_admin_crea_el_primer_administrador(db_session, monkeypatch):
    """En producción el único camino era seed_demo, que carga pacientes y profesionales falsos."""
    codigo = _run_create_admin(
        monkeypatch,
        ADMIN_USERNAME="Maria",
        ADMIN_PASSWORD="una-clave-larga",
        ADMIN_FULL_NAME="María Pérez",
        ADMIN_EMAIL="maria@consultorio.com",
    )

    db_session.expire_all()
    usuario = db_session.scalar(select(User).where(User.username == "maria"))
    assert codigo == 0
    assert usuario.role == UserRole.ADMIN and usuario.is_active
    assert usuario.password_hash != "una-clave-larga"


def test_create_admin_no_pisa_un_usuario_existente(db_session, monkeypatch):
    """El job puede reintentarse: no debe cambiar la contraseña de alguien que ya entra."""
    _run_create_admin(
        monkeypatch, ADMIN_USERNAME="maria", ADMIN_PASSWORD="una-clave-larga",
        ADMIN_FULL_NAME="María Pérez", ADMIN_EMAIL="maria@consultorio.com",
    )
    db_session.expire_all()
    hash_original = db_session.scalar(select(User).where(User.username == "maria")).password_hash

    codigo = _run_create_admin(
        monkeypatch, ADMIN_USERNAME="maria", ADMIN_PASSWORD="otra-clave-distinta",
        ADMIN_FULL_NAME="Otra Persona", ADMIN_EMAIL="otra@consultorio.com",
    )

    db_session.expire_all()
    assert codigo == 0
    assert db_session.scalar(select(User).where(User.username == "maria")).password_hash == hash_original


def test_create_admin_rechaza_datos_incompletos_o_debiles(db_session, monkeypatch):
    sin_variables = _run_create_admin(monkeypatch)
    clave_corta = _run_create_admin(
        monkeypatch, ADMIN_USERNAME="maria", ADMIN_PASSWORD="corta",
        ADMIN_FULL_NAME="María Pérez", ADMIN_EMAIL="maria@consultorio.com",
    )

    assert (sin_variables, clave_corta) == (2, 2)
    assert db_session.scalars(select(User)).all() == []


def test_a_professional_name_is_validated_like_a_patient_name(client, db_session, clinic):
    """El nombre se publica en /reservar: uno vacío dejaba una opción fantasma para elegir."""
    login(client, "admin")
    for first_name, last_name in (("X1", "Gómez"), ("   ", "   "), ("Laura", "G0mez")):
        response = client.post(
            "/app/professionals",
            data={
                "first_name": first_name,
                "last_name": last_name,
                "specialty": "",
                "email": "",
                "phone": "",
                "default_appointment_duration": "30",
                "deposit_amount": "",
            },
            follow_redirects=False,
        )
        assert "error=" in response.headers["location"], f"aceptó «{first_name} {last_name}»"
