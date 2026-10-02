"""Guarantees that only exist on PostgreSQL (run with TEST_DATABASE_URL pointing to PostgreSQL)."""

import threading
from datetime import date, datetime, time

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.enums import AppointmentStatus
from app.core.exceptions import DomainError
from app.db import session as db_session_module
from app.db.base import Base
from app.integrations.email import EmailClient
from app.models.appointment import Appointment
from app.models.availability_window import AvailabilityWindow
from app.models.patient import Patient
from app.models.professional import Professional
from app.schemas.appointment import AppointmentCreate
from app.services.followup_service import FollowUpService
from app.services.reception_service import ReceptionService
from app.services.schedule_service import ScheduleService

pytestmark = pytest.mark.skipif(
    get_settings().database_url.startswith("sqlite"),
    reason="PostgreSQL-only guarantees; set TEST_DATABASE_URL to run them",
)


def seed_calendar(db):
    professional = Professional(first_name="Laura", last_name="Gomez", default_appointment_duration=30)
    patients = [
        Patient(dni="30111222", first_name="Ana", last_name="Perez"),
        Patient(dni="30111333", first_name="Juan", last_name="Diaz"),
    ]
    db.add_all([professional, *patients])
    db.flush()
    db.add(
        AvailabilityWindow(
            professional_id=professional.id,
            availability_date=date(2026, 3, 30),
            start_time=time(9, 0),
            end_time=time(12, 0),
            slot_duration_minutes=30,
        )
    )
    db.commit()
    return professional.id, [patient.id for patient in patients]


def test_models_match_migrations():
    with db_session_module.engine.connect() as connection:
        diffs = compare_metadata(MigrationContext.configure(connection, opts={"compare_type": True}), Base.metadata)
    assert diffs == []


def test_database_rejects_overlapping_active_appointments(db_session):
    professional_id, (first_patient, second_patient) = seed_calendar(db_session)

    def appointment(patient_id, starts_at, status=AppointmentStatus.RESERVED):
        return Appointment(
            patient_id=patient_id,
            professional_id=professional_id,
            starts_at=starts_at,
            ends_at=starts_at.replace(minute=starts_at.minute + 30),
            duration_minutes=30,
            status=status,
            created_by="test",
        )

    db_session.add(appointment(first_patient, datetime(2026, 3, 30, 9, 0), AppointmentStatus.CANCELLED))
    db_session.add(appointment(second_patient, datetime(2026, 3, 30, 9, 0)))
    db_session.commit()

    db_session.add(appointment(first_patient, datetime(2026, 3, 30, 9, 15)))
    with pytest.raises(IntegrityError, match="no_overlap"):
        db_session.commit()
    db_session.rollback()


def test_concurrent_bookings_of_the_same_slot_only_one_wins(db_session):
    professional_id, patient_ids = seed_calendar(db_session)
    settings = get_settings()
    barrier = threading.Barrier(len(patient_ids))
    outcomes: list[str] = []

    def attempt(patient_id: int) -> None:
        session = db_session_module.SessionLocal()
        schedule_service = ScheduleService(settings)
        try:
            barrier.wait()
            schedule_service.create_appointment(
                session,
                AppointmentCreate(
                    professional_id=professional_id,
                    patient_id=patient_id,
                    starts_at=datetime(2026, 3, 30, 10, 0),
                    duration_minutes=30,
                    created_by="test",
                ),
                reception_service=ReceptionService(),
                followup_service=FollowUpService(settings, EmailClient(settings)),
                actor="test",
            )
            outcomes.append("booked")
        except DomainError as exc:
            outcomes.append(exc.detail)
        finally:
            session.close()

    threads = [threading.Thread(target=attempt, args=(patient_id,)) for patient_id in patient_ids]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert sorted(outcomes) == sorted(["booked", "Ese horario ya no está disponible. Elegí otro, por favor."])
