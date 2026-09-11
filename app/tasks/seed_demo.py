"""Load demo data: staff users, two professionals, two weeks of availability and sample patients.

Idempotent: running it twice does not duplicate anything.
"""

from datetime import datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import inspect, select

from app.core import clock
from app.core.config import get_settings
from app.core.enums import UserRole
from app.db.session import SessionLocal
from app.integrations.email import EmailClient
from app.models.appointment import Appointment
from app.models.availability_window import AvailabilityWindow
from app.schemas.appointment import AppointmentCreate
from app.schemas.auth import UserCreate
from app.schemas.availability import AvailabilityWindowCreate
from app.schemas.patient import PatientCreate
from app.schemas.professional import ProfessionalCreate
from app.services.auth_service import AuthService
from app.services.followup_agent import FollowUpAgent
from app.services.professional_service import ProfessionalService
from app.services.reception_agent import ReceptionAgent
from app.services.schedule_agent import ScheduleAgent

DEMO_PASSWORD = "demo12345"
BUSINESS_DAYS = 10


def _ensure_schema_ready(db) -> None:
    # Table names come from the model class names (singular), see app/db/base.py.
    required_tables = [
        "user",
        "patient",
        "professional",
        "availability_window",
        "appointment",
        "notification",
        "payment",
        "audit_log",
    ]
    inspector = inspect(db.get_bind())
    missing = [table for table in required_tables if not inspector.has_table(table)]
    if missing:
        raise RuntimeError(
            "Database schema is not initialized. Run 'alembic upgrade head' before seeding demo data. "
            f"Missing tables: {', '.join(missing)}"
        )


def _next_business_days(count: int):
    day = clock.today() + timedelta(days=1)
    while count:
        if day.weekday() < 5:
            yield day
            count -= 1
        day += timedelta(days=1)


def main() -> None:
    db = SessionLocal()
    settings = get_settings()
    _ensure_schema_ready(db)
    auth_service = AuthService(settings)
    reception_agent = ReceptionAgent()
    professional_service = ProfessionalService()
    schedule_agent = ScheduleAgent(settings)
    followup_agent = FollowUpAgent(settings=settings, email_client=EmailClient(settings))

    try:
        for username, full_name, role in (
            ("admin", "Admin Demo", UserRole.ADMIN),
            ("recepcion", "Recepción Demo", UserRole.RECEPTIONIST),
        ):
            if not auth_service.get_user_by_username(db, username):
                auth_service.create_user(
                    db,
                    UserCreate(
                        username=username,
                        full_name=full_name,
                        email=f"{username}@example.com",
                        password=DEMO_PASSWORD,
                        role=role,
                    ),
                )

        professionals = professional_service.list_professionals(db)
        if not professionals:
            professional_service.create_professional(
                db,
                ProfessionalCreate(
                    first_name="Laura",
                    last_name="Gómez",
                    specialty="Odontología general",
                    email="laura@example.com",
                    phone="+5491122222222",
                    default_appointment_duration=30,
                    deposit_amount=Decimal("10000"),
                ),
            )
            professional_service.create_professional(
                db,
                ProfessionalCreate(
                    first_name="Martín",
                    last_name="Suárez",
                    specialty="Ortodoncia",
                    email="martin@example.com",
                    phone="+5491133333333",
                    default_appointment_duration=45,
                    deposit_amount=Decimal("0"),
                ),
            )
            professionals = professional_service.list_professionals(db)

        days = list(_next_business_days(BUSINESS_DAYS))
        for index, professional in enumerate(professionals[:2]):
            if db.scalar(select(AvailabilityWindow.id).where(AvailabilityWindow.professional_id == professional.id)):
                continue
            for day in days:
                if index == 0:
                    start, end, note = time(9, 0), time(13, 0), "Mañana"
                elif day.weekday() in (0, 2, 4):
                    start, end, note = time(14, 0), time(18, 30), "Tarde"
                else:
                    continue
                schedule_agent.create_availability_window(
                    db,
                    AvailabilityWindowCreate(
                        professional_id=professional.id,
                        availability_date=day,
                        start_time=start,
                        end_time=end,
                        slot_duration_minutes=professional.default_appointment_duration,
                        notes=note,
                    ),
                    actor="seed_demo",
                )

        patients = reception_agent.list_patients(db)
        if not patients:
            for dni, first_name, last_name, email, phone, observations in (
                ("30111222", "Ana", "Pérez", "ana@example.com", "11 4444-4444", "Control anual"),
                ("28999888", "Mateo", "López", "mateo@example.com", "11 5555-5555", "Consulta por dolor"),
            ):
                reception_agent.create_patient(
                    db,
                    PatientCreate(
                        dni=dni,
                        first_name=first_name,
                        last_name=last_name,
                        email=email,
                        phone=phone,
                        observations=observations,
                    ),
                )
            patients = reception_agent.list_patients(db)

        if not db.scalar(select(Appointment.id)) and professionals and patients and days:
            schedule_agent.create_appointment(
                db,
                AppointmentCreate(
                    professional_id=professionals[0].id,
                    patient_id=patients[0].id,
                    starts_at=datetime.combine(days[0], time(10, 0)),
                    duration_minutes=professionals[0].default_appointment_duration,
                    reason="Limpieza",
                    notes="Turno demo",
                    created_by="seed_demo",
                ),
                reception_agent=reception_agent,
                followup_agent=followup_agent,
                actor="seed_demo",
            )

        print("Demo data ready.")
        print(f"admin / {DEMO_PASSWORD}")
        print(f"recepcion / {DEMO_PASSWORD}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
