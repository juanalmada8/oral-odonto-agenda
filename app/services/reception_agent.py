"""Reception agent: validates incoming requests and resolves patient identity."""

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.core.enums import AppointmentStatus
from app.core.exceptions import DomainError
from app.models.appointment import Appointment
from app.models.notification import Notification
from app.models.patient import Patient
from app.schemas.booking import PublicBookingRequest
from app.schemas.patient import PatientCreate, PatientUpdate, PatientUpsert
from app.utils.audit import create_audit_log
from app.utils.validation import names_match


class ReceptionAgent:
    def list_patients(self, db: Session) -> list[Patient]:
        return list(db.scalars(select(Patient).order_by(Patient.last_name, Patient.first_name)))

    def get_patient(self, db: Session, patient_id: int) -> Patient:
        patient = db.get(Patient, patient_id)
        if not patient:
            raise DomainError("No encontramos el paciente.", status_code=404)
        return patient

    def create_patient(self, db: Session, payload: PatientCreate, actor: str = "reception_agent") -> Patient:
        self._assert_unique_dni(db, dni=payload.dni)
        patient = Patient(**payload.model_dump())
        db.add(patient)
        db.flush()
        create_audit_log(
            db,
            action="patient.created",
            entity_name="patient",
            entity_id=str(patient.id),
            actor=actor,
            description="Patient created",
        )
        db.commit()
        db.refresh(patient)
        return patient

    def update_patient(self, db: Session, patient_id: int, payload: PatientUpdate, actor: str = "reception_agent") -> Patient:
        patient = self.get_patient(db, patient_id)
        changes = payload.model_dump(exclude_unset=True)
        if "dni" in changes:
            self._assert_unique_dni(
                db,
                dni=changes["dni"],
                exclude_id=patient.id,
            )
        for field, value in changes.items():
            setattr(patient, field, value)
        create_audit_log(
            db,
            action="patient.updated",
            entity_name="patient",
            entity_id=str(patient.id),
            actor=actor,
            description="Patient updated",
            details=changes,
        )
        db.commit()
        db.refresh(patient)
        return patient

    def deactivate_patient(self, db: Session, patient_id: int, actor: str = "reception_agent") -> Patient:
        patient = self.get_patient(db, patient_id)
        patient.is_active = False
        create_audit_log(
            db,
            action="patient.deactivated",
            entity_name="patient",
            entity_id=str(patient.id),
            actor=actor,
            description="Patient deactivated",
        )
        db.commit()
        db.refresh(patient)
        return patient

    def delete_patient(self, db: Session, patient_id: int, actor: str = "reception_agent") -> None:
        patient = self.get_patient(db, patient_id)
        has_active_appointments = db.scalar(
            select(Appointment.id)
            .where(Appointment.patient_id == patient.id)
            .where(Appointment.status.in_([AppointmentStatus.RESERVED, AppointmentStatus.CONFIRMED]))
            .limit(1)
        )
        if has_active_appointments:
            raise DomainError(
                "No se puede borrar el paciente porque tiene turnos activos (reservados o confirmados).",
                status_code=409,
            )

        appointment_ids = list(db.scalars(select(Appointment.id).where(Appointment.patient_id == patient.id)))
        if appointment_ids:
            db.execute(
                update(Notification)
                .where(Notification.appointment_id.in_(appointment_ids))
                .values(appointment_id=None)
            )
            db.execute(delete(Appointment).where(Appointment.id.in_(appointment_ids)))

        db.execute(
            update(Notification)
            .where(Notification.patient_id == patient.id)
            .values(patient_id=None)
        )

        create_audit_log(
            db,
            action="patient.deleted",
            entity_name="patient",
            entity_id=str(patient.id),
            actor=actor,
            description="Patient deleted",
        )
        db.delete(patient)
        db.commit()

    def resolve_patient(
        self,
        db: Session,
        *,
        patient_id: int | None = None,
        patient_payload: PatientUpsert | None = None,
        actor: str = "reception_agent",
    ) -> Patient:
        if patient_id is not None:
            patient = self.get_patient(db, patient_id)
            if not patient.is_active:
                raise DomainError("El paciente está inactivo.", status_code=409)
            return patient

        if patient_payload is None:
            raise DomainError("Faltan los datos del paciente.", status_code=422)

        patient = self._find_existing(db, dni=patient_payload.dni)
        if patient:
            updated_fields = {}
            for field, value in patient_payload.model_dump().items():
                if value and getattr(patient, field) != value:
                    setattr(patient, field, value)
                    updated_fields[field] = value
            if updated_fields:
                create_audit_log(
                    db,
                    action="patient.updated_from_booking",
                    entity_name="patient",
                    entity_id=str(patient.id),
                    actor=actor,
                    description="Patient enriched during booking",
                    details=updated_fields,
                )
                db.flush()
            return patient

        patient = Patient(**patient_payload.model_dump())
        db.add(patient)
        db.flush()
        create_audit_log(
            db,
            action="patient.created_from_booking",
            entity_name="patient",
            entity_id=str(patient.id),
            actor=actor,
            description="Patient created during booking flow",
        )
        return patient

    def resolve_patient_for_public_booking(self, db: Session, request: PublicBookingRequest) -> Patient:
        """Find or create the patient behind a public booking without trusting the form.

        Anyone can type any DNI on the public site, so an existing record is only matched when the
        last name agrees, and its stored data is never overwritten (only empty fields are filled).
        Contact data for the booking itself lives on the appointment.
        """
        patient = self._find_existing(db, dni=request.dni)
        if patient is None:
            patient = Patient(
                dni=request.dni,
                first_name=request.first_name,
                last_name=request.last_name,
                email=request.email,
                phone=request.phone,
                observations=request.observations,
            )
            db.add(patient)
            db.flush()
            create_audit_log(
                db,
                action="patient.created_from_booking",
                entity_name="patient",
                entity_id=str(patient.id),
                actor="public_booking",
                description="Patient created during public booking",
            )
            return patient

        if not patient.is_active:
            raise DomainError(
                "No podemos tomar reservas online para ese DNI. Comunicate con el consultorio.",
                status_code=409,
            )
        if not names_match(patient.last_name, request.last_name):
            raise DomainError(
                "Los datos no coinciden con los registrados para ese DNI. "
                "Revisá el apellido o comunicate con el consultorio.",
                status_code=409,
            )
        filled = {}
        for field in ("email", "phone", "observations"):
            value = getattr(request, field)
            if value and not getattr(patient, field):
                setattr(patient, field, value)
                filled[field] = value
        if filled:
            create_audit_log(
                db,
                action="patient.completed_from_booking",
                entity_name="patient",
                entity_id=str(patient.id),
                actor="public_booking",
                description="Empty patient fields filled during public booking",
                details=filled,
            )
            db.flush()
        return patient

    def _find_existing(self, db: Session, *, dni: str) -> Patient | None:
        return db.scalar(select(Patient).where(Patient.dni == dni))

    def _assert_unique_dni(
        self,
        db: Session,
        *,
        dni: str,
        exclude_id: int | None = None,
    ) -> None:
        query = select(Patient).where(Patient.dni == dni)
        if exclude_id:
            query = query.where(Patient.id != exclude_id)
        existing = db.scalar(query)
        if existing:
            raise DomainError("Ya existe un paciente con ese DNI.", status_code=409)
