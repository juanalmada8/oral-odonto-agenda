from sqlalchemy import JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin


class AuditLog(TimestampMixin, Base):
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    entity_name: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    entity_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    actor: Mapped[str] = mapped_column(String(80), nullable=False, default="system", server_default="system")
    description: Mapped[str | None] = mapped_column(Text())
    details: Mapped[dict | None] = mapped_column(JSON)
