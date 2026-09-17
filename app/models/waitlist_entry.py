from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import WaitlistPeriod, WaitlistStatus
from app.db.base import Base
from app.db.types import enum_column
from app.models.mixins import TimestampMixin


class WaitlistEntry(TimestampMixin, Base):
    """Alguien que quiere turno antes de lo que hay disponible.

    Cuando se libera un horario (cancelación o seña vencida) se le avisa al primero
    que encaje. No se le reserva el horario: se le manda el link y reserva como todos,
    así el turno no queda bloqueado si no contesta.
    """

    __tablename__ = "waitlist_entry"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patient.id", ondelete="CASCADE"), nullable=False, index=True)
    # Sin profesional significa "me sirve cualquiera".
    professional_id: Mapped[int | None] = mapped_column(ForeignKey("professional.id", ondelete="CASCADE"), index=True)
    date_from: Mapped[date] = mapped_column(Date(), nullable=False)
    date_to: Mapped[date] = mapped_column(Date(), nullable=False)
    period: Mapped[WaitlistPeriod] = mapped_column(
        enum_column(WaitlistPeriod),
        nullable=False,
        default=WaitlistPeriod.ANY,
        server_default=WaitlistPeriod.ANY.value,
    )
    status: Mapped[WaitlistStatus] = mapped_column(
        enum_column(WaitlistStatus),
        nullable=False,
        default=WaitlistStatus.WAITING,
        server_default=WaitlistStatus.WAITING.value,
        index=True,
    )
    contact_email: Mapped[str | None] = mapped_column(String(255))
    contact_phone: Mapped[str | None] = mapped_column(String(40))
    notes: Mapped[str | None] = mapped_column(Text())
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    notified_slot_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))

    patient = relationship("Patient")
    professional = relationship("Professional")

    def covers(self, slot_starts_at: datetime) -> bool:
        """Si el horario liberado le sirve a esta persona."""
        if not (self.date_from <= slot_starts_at.date() <= self.date_to):
            return False
        if self.period == WaitlistPeriod.MORNING:
            return slot_starts_at.hour < 13
        if self.period == WaitlistPeriod.AFTERNOON:
            return slot_starts_at.hour >= 13
        return True
