from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.exceptions import DomainError
from app.models.appointment import Appointment
from app.models.professional import Professional
from app.schemas.professional import ProfessionalCreate, ProfessionalUpdate
from app.utils.audit import create_audit_log


class ProfessionalService:
    def list_professionals(self, db: Session) -> list[Professional]:
        return list(db.scalars(select(Professional).order_by(Professional.last_name, Professional.first_name)))

    def get_professional(self, db: Session, professional_id: int) -> Professional:
        professional = db.get(Professional, professional_id)
        if not professional:
            raise DomainError("Professional not found", status_code=404)
        return professional

    def create_professional(self, db: Session, payload: ProfessionalCreate, actor: str = "admin") -> Professional:
        self._assert_unique_contact(db, payload.email, payload.phone)
        professional = Professional(**payload.model_dump())
        db.add(professional)
        db.flush()
        create_audit_log(
            db,
            action="professional.created",
            entity_name="professional",
            entity_id=str(professional.id),
            actor=actor,
            description="Professional created",
        )
        db.commit()
        db.refresh(professional)
        return professional

    def update_professional(
        self,
        db: Session,
        professional_id: int,
        payload: ProfessionalUpdate,
        actor: str = "admin",
    ) -> Professional:
        professional = self.get_professional(db, professional_id)
        changes = payload.model_dump(exclude_unset=True)
        if "email" in changes or "phone" in changes:
            self._assert_unique_contact(
                db,
                changes.get("email", professional.email),
                changes.get("phone", professional.phone),
                exclude_id=professional.id,
            )
        for field, value in changes.items():
            setattr(professional, field, value)
        create_audit_log(
            db,
            action="professional.updated",
            entity_name="professional",
            entity_id=str(professional.id),
            actor=actor,
            description="Professional updated",
            details=changes,
        )
        db.commit()
        db.refresh(professional)
        return professional

    def deactivate_professional(self, db: Session, professional_id: int, actor: str = "admin") -> Professional:
        professional = self.get_professional(db, professional_id)
        professional.is_active = False
        create_audit_log(
            db,
            action="professional.deactivated",
            entity_name="professional",
            entity_id=str(professional.id),
            actor=actor,
            description="Professional deactivated",
        )
        db.commit()
        db.refresh(professional)
        return professional

    def delete_professional(self, db: Session, professional_id: int, actor: str = "admin") -> None:
        professional = self.get_professional(db, professional_id)
        has_history = db.scalar(select(Appointment.id).where(Appointment.professional_id == professional.id).limit(1))
        if has_history:
            raise DomainError(
                "No se puede borrar el profesional porque tiene historial de turnos. Podés editarlo o desactivarlo.",
                status_code=409,
            )
        create_audit_log(
            db,
            action="professional.deleted",
            entity_name="professional",
            entity_id=str(professional.id),
            actor=actor,
            description="Professional deleted",
        )
        db.delete(professional)
        db.commit()

    def _assert_unique_contact(
        self,
        db: Session,
        email: str | None,
        phone: str | None,
        exclude_id: int | None = None,
    ) -> None:
        filters = []
        if email:
            filters.append(Professional.email == email)
        if phone:
            filters.append(Professional.phone == phone)
        if not filters:
            return
        query = select(Professional).where(or_(*filters))
        if exclude_id:
            query = query.where(Professional.id != exclude_id)
        if db.scalar(query):
            raise DomainError("A professional already exists with the same email or phone", status_code=409)
