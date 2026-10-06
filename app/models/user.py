from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import UserRole
from app.db.base import Base
from app.db.types import enum_column
from app.models.mixins import TimestampMixin


class User(TimestampMixin, Base):
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        enum_column(UserRole),
        nullable=False,
        default=UserRole.RECEPTIONIST,
        server_default=UserRole.RECEPTIONIST.value,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    # Goes into every session token. Bumping it (on a password change) invalidates the sessions issued
    # before, so someone who stole a session is kicked out as soon as the password changes.
    session_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # Set for role=professional: the dentist this login belongs to (their agenda and availability).
    professional_id: Mapped[int | None] = mapped_column(
        ForeignKey("professional.id", ondelete="SET NULL"),
        unique=True,
        index=True,
    )

    professional = relationship("Professional")
