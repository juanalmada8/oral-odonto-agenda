from datetime import date, datetime, timedelta, time

from sqlalchemy import select

from app.core.config import get_settings
from app.core.enums import AppointmentStatus, UserRole
from app.db.base import Base
from app.db.session import SessionLocal
from app.db import models  # noqa: F401
from app.models.availability_window import AvailabilityWindow
from app.models.appointment import Appointment
from app.models.patient import Patient
from app.models.professional import Professional
from app.models.user import User
from app.schemas.auth import UserCreate
from app.schemas.availability import AvailabilityWindowCreate
from app.schemas.patient import PatientCreate
from app.schemas.professional import ProfessionalCreate
from app.services.auth_service import AuthService
from app.services.followup_agent import FollowUpAgent
from app.services.professional_service import ProfessionalService
from app.services.reception_agent import ReceptionAgent
from app.services.schedule_agent import ScheduleAgent
from app.integrations.email import EmailClient
from app.schemas.appointment import AppointmentCreate


def main() -> None:
    db = SessionLocal()
    settings = get_settings()
    Base.metadata.create_all(bind=db.get_bind())
    auth_service = AuthService(settings)
    reception_agent = ReceptionAgent()
    professional_service = ProfessionalService()
    schedule_agent = ScheduleAgent(timezone_name=settings.app_timezone)
    followup_agent = FollowUpAgent(settings=settings, email_client=EmailClient(settings))

    try:
        if not auth_service.get_user_by_username(db, "admin"):
            auth_service.create_user(
                db,
                UserCreate(
                    username="admin",
                    full_name="Admin Demo",
                    email="admin@example.com",
                    password="demo12345",
                    role=UserRole.ADMIN,
                ),
            )

        if not auth_service.get_user_by_username(db, "recepcion"):
            auth_service.create_user(
                db,
                UserCreate(
                    username="recepcion",
                    full_name="Recepcion Demo",
                    email="recepcion@example.com",
                    password="demo12345",
                    role=UserRole.RECEPTIONIST,
                ),
            )

        professionals = professional_service.list_professionals(db)
        if not professionals:
            professional_service.create_professional(
                db,
                ProfessionalCreate(
                    first_name="Laura",
                    last_name="Gomez",
                    specialty="Odontologia general",
                    email="laura@example.com",
                    phone="+5491122222222",
                    default_appointment_duration=30,
                ),
            )
            professional_service.create_professional(
                db,
                ProfessionalCreate(
                    first_name="Martin",
                    last_name="Suarez",
                    specialty="Ortodoncia",
                    email="martin@example.com",
                    phone="+5491133333333",
                    default_appointment_duration=45,
                ),
            )
            professionals = professional_service.list_professionals(db)

        target_day = date.today() + timedelta(days=1)
        while target_day.weekday() > 4:
            target_day += timedelta(days=1)
        second_day = target_day + timedelta(days=2)

        for index, professional in enumerate(professionals):
            existing_window = db.scalar(select(AvailabilityWindow).where(AvailabilityWindow.professional_id == professional.id))
            if existing_window:
                continue
            if index == 0:
                schedule_agent.create_availability_window(
                    db,
                    AvailabilityWindowCreate(
                        professional_id=professional.id,
                        availability_date=target_day,
                        start_time=time(9, 0),
                        end_time=time(13, 0),
                        slot_duration_minutes=professional.default_appointment_duration,
                        notes="Jornada demo",
                    ),
                )
            else:
                schedule_agent.create_availability_window(
                    db,
                    AvailabilityWindowCreate(
                        professional_id=professional.id,
                        availability_date=target_day,
                        start_time=time(10, 0),
                        end_time=time(13, 0),
                        slot_duration_minutes=professional.default_appointment_duration,
                        notes="Bloque demo mañana",
                    ),
                )
                schedule_agent.create_availability_window(
                    db,
                    AvailabilityWindowCreate(
                        professional_id=professional.id,
                        availability_date=second_day,
                        start_time=time(11, 30),
                        end_time=time(12, 15),
                        slot_duration_minutes=professional.default_appointment_duration,
                        notes="Disponibilidad puntual",
                    ),
                )

        patients = reception_agent.list_patients(db)
        if not patients:
            reception_agent.create_patient(
                db,
                PatientCreate(
                    dni="30111222",
                    first_name="Ana",
                    last_name="Perez",
                    email="ana@example.com",
                    phone="+5491144444444",
                    observations="Control anual",
                ),
            )
            reception_agent.create_patient(
                db,
                PatientCreate(
                    dni="28999888",
                    first_name="Mateo",
                    last_name="Lopez",
                    email="mateo@example.com",
                    phone="+5491155555555",
                    observations="Consulta por dolor",
                ),
            )
            patients = reception_agent.list_patients(db)

        has_appointments = db.scalar(select(Appointment.id))
        if not has_appointments and professionals and patients:
            starts_at = datetime.combine(target_day, time(9, 0))
            first_professional = professionals[0]
            second_professional = professionals[-1]
            schedule_agent.create_appointment(
                db,
                payload=AppointmentCreate(
                    professional_id=first_professional.id,
                    patient_id=patients[0].id,
                    starts_at=starts_at,
                    duration_minutes=30,
                    reason="Limpieza",
                    notes="Turno demo",
                    created_by="seed_demo",
                ),
                reception_agent=reception_agent,
                followup_agent=followup_agent,
                actor="seed_demo",
            )
            schedule_agent.create_appointment(
                db,
                payload=AppointmentCreate(
                    professional_id=second_professional.id,
                    patient_id=patients[-1].id,
                    starts_at=starts_at + timedelta(minutes=60),
                    duration_minutes=second_professional.default_appointment_duration,
                    reason="Control",
                    notes="Turno demo",
                    created_by="seed_demo",
                ),
                reception_agent=reception_agent,
                followup_agent=followup_agent,
                actor="seed_demo",
            )
        print("Demo data ready.")
        print("admin / demo12345")
        print("recepcion / demo12345")
    finally:
        db.close()


if __name__ == "__main__":
    main()
