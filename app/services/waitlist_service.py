"""Lista de espera: a quién avisarle cuando se libera un horario."""

import logging
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.enums import WaitlistStatus
from app.core.exceptions import DomainError
from app.models.appointment import Appointment
from app.models.waitlist_entry import WaitlistEntry
from app.schemas.waitlist import WaitlistJoin
from app.services.followup_service import FollowUpService
from app.utils.audit import create_audit_log

logger = logging.getLogger(__name__)


class WaitlistService:
    def join(self, db: Session, patient_id: int, payload: WaitlistJoin, *, actor: str = "waitlist") -> WaitlistEntry:
        if payload.date_to < payload.date_from:
            raise DomainError("La fecha de fin no puede ser anterior a la de inicio.")
        existing = db.scalar(
            select(WaitlistEntry)
            .where(WaitlistEntry.patient_id == patient_id)
            .where(WaitlistEntry.status == WaitlistStatus.WAITING)
            .where(WaitlistEntry.professional_id == payload.professional_id)
        )
        if existing:
            # Anotarse dos veces por lo mismo no agrega nada: se actualiza lo que ya había.
            existing.date_from, existing.date_to = payload.date_from, payload.date_to
            existing.period = payload.period
            existing.contact_email = payload.contact_email
            existing.contact_phone = payload.contact_phone
            existing.notes = payload.notes
            db.commit()
            return existing

        entry = WaitlistEntry(
            patient_id=patient_id,
            professional_id=payload.professional_id,
            date_from=payload.date_from,
            date_to=payload.date_to,
            period=payload.period,
            contact_email=payload.contact_email,
            contact_phone=payload.contact_phone,
            notes=payload.notes,
        )
        db.add(entry)
        db.flush()
        create_audit_log(
            db,
            action="waitlist.joined",
            entity_name="waitlist_entry",
            entity_id=str(entry.id),
            actor=actor,
            description="Paciente anotado en la lista de espera",
            details={"professional_id": payload.professional_id, "from": payload.date_from, "to": payload.date_to},
        )
        db.commit()
        return entry

    def list_entries(self, db: Session, *, professional_id: int | None = None, limit: int = 200) -> list[WaitlistEntry]:
        query = select(WaitlistEntry).order_by(WaitlistEntry.status, WaitlistEntry.created_at).limit(limit)
        if professional_id:
            query = query.where(WaitlistEntry.professional_id == professional_id)
        return list(db.scalars(query))

    def waiting_count(self, db: Session) -> int:
        return len(
            list(db.scalars(select(WaitlistEntry.id).where(WaitlistEntry.status == WaitlistStatus.WAITING)))
        )

    def set_status(self, db: Session, entry_id: int, status: WaitlistStatus, *, actor: str) -> WaitlistEntry:
        entry = db.get(WaitlistEntry, entry_id)
        if entry is None:
            raise DomainError("No encontramos esa anotación en la lista de espera.", status_code=404)
        entry.status = status
        create_audit_log(
            db,
            action=f"waitlist.{status.value}",
            entity_name="waitlist_entry",
            entity_id=str(entry.id),
            actor=actor,
            description="Estado de la lista de espera actualizado",
        )
        db.commit()
        return entry

    def notify_freed_slot(
        self,
        db: Session,
        appointment: Appointment,
        *,
        followup_service: FollowUpService | None = None,
        limit: int = 3,
    ) -> list[WaitlistEntry]:
        """Ofrece el horario liberado a los primeros de la lista que le sirva.

        Se avisa a unos pocos y no a uno solo: si el primero no contesta el hueco se
        pierde igual. Nadie queda con el horario reservado, reservan por la web como todos.
        """
        if followup_service is None or appointment.starts_at <= clock.now():
            return []

        candidates = db.scalars(
            select(WaitlistEntry)
            .where(WaitlistEntry.status == WaitlistStatus.WAITING)
            # Con IN (id, NULL) las filas NULL no matchean, y NULL acá significa
            # "me sirve cualquier profesional": quedaban afuera de todos los avisos.
            .where(
                or_(
                    WaitlistEntry.professional_id == appointment.professional_id,
                    WaitlistEntry.professional_id.is_(None),
                )
            )
            .where(WaitlistEntry.patient_id != appointment.patient_id)
            .order_by(WaitlistEntry.created_at)
        )

        notified: list[WaitlistEntry] = []
        for entry in candidates:
            if len(notified) >= limit:
                break
            if not entry.covers(appointment.starts_at):
                continue
            if followup_service.queue_waitlist_offer(db, entry, appointment) is None:
                continue
            entry.status = WaitlistStatus.NOTIFIED
            entry.notified_at = clock.now()
            entry.notified_slot_at = appointment.starts_at
            notified.append(entry)

        if notified:
            logger.info(
                "Freed slot %s offered to %d waitlist entries", appointment.starts_at.isoformat(), len(notified)
            )
        return notified

    def mark_booked_for(self, db: Session, patient_id: int, starts_at: datetime) -> None:
        """Al reservar, se cierra la anotación de quien estaba esperando ese horario."""
        entries = db.scalars(
            select(WaitlistEntry)
            .where(WaitlistEntry.patient_id == patient_id)
            .where(WaitlistEntry.status.in_([WaitlistStatus.WAITING, WaitlistStatus.NOTIFIED]))
        )
        for entry in entries:
            if entry.covers(starts_at):
                entry.status = WaitlistStatus.BOOKED
