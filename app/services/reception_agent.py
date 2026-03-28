"""Reception agent: validates incoming requests and resolves patient identity."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import DomainError
from app.models.appointment import Appointment
from app.models.patient import Patient
from app.schemas.patient import PatientCreate, PatientUpdate, PatientUpsert
from app.utils.audit import create_audit_log


class ReceptionAgent:
    def list_patients(self, db: Session) -> list[Patient]:
        return list(db.scalars(select(Patient).order_by(Patient.last_name, Patient.first_name)))

    def get_patient(self, db: Session, patient_id: int) -> Patient:
        patient = db.get(Patient, patient_id)
        if not patient:
            raise DomainError("Patient not found", status_code=404)
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
        has_history = db.scalar(select(Appointment.id).where(Appointment.patient_id == patient.id).limit(1))
        if has_history:
            raise DomainError(
                "No se puede borrar el paciente porque tiene historial de turnos. Desactivalo o editalo.",
                status_code=409,
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
                raise DomainError("Patient is inactive", status_code=409)
            return patient

        if patient_payload is None:
            raise DomainError("Patient information is required", status_code=422)

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
            raise DomainError("A patient already exists with the same DNI", status_code=409)
