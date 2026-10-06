from fastapi import Response
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.enums import UserRole
from app.core.exceptions import DomainError
from app.core.security import create_access_token, decode_access_token, hash_password, verify_password
from app.models.professional import Professional
from app.models.user import User
from app.schemas.auth import UserCreate, UserUpdate
from app.utils.audit import create_audit_log


class AuthService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def list_users(self, db: Session) -> list[User]:
        return list(db.scalars(select(User).order_by(User.username)))

    def get_user_by_username(self, db: Session, username: str) -> User | None:
        return db.scalar(select(User).where(User.username == username))

    def get_user_by_id(self, db: Session, user_id: int) -> User | None:
        return db.get(User, user_id)

    def create_user(self, db: Session, payload: UserCreate, actor: str = "system") -> User:
        existing = db.scalar(select(User).where(or_(User.username == payload.username, User.email == payload.email)))
        if existing:
            raise DomainError("Ya existe un usuario con ese nombre de usuario o email.", status_code=409)
        self._validate_professional_link(db, payload.role, payload.professional_id)
        user = User(
            username=payload.username,
            full_name=payload.full_name,
            email=str(payload.email),
            password_hash=hash_password(payload.password),
            role=payload.role,
            professional_id=payload.professional_id,
        )
        db.add(user)
        db.flush()
        create_audit_log(
            db,
            action="user.created",
            entity_name="user",
            entity_id=str(user.id),
            actor=actor,
            description="User created",
            details={"role": user.role.value, "username": user.username},
        )
        db.commit()
        db.refresh(user)
        return user

    def update_user(self, db: Session, user_id: int, payload: UserUpdate, *, actor: User) -> User:
        user = self.get_user_by_id(db, user_id)
        if not user:
            raise DomainError("No encontramos el usuario.", status_code=404)
        changes = payload.model_dump(exclude_unset=True)
        role = changes.get("role", user.role)
        professional_id = changes.get("professional_id", user.professional_id) if role == UserRole.PROFESSIONAL else None
        if user.id == actor.id and (changes.get("is_active") is False or role != user.role):
            raise DomainError("No podés desactivarte ni cambiar tu propio rol.", status_code=409)
        if user.role == UserRole.ADMIN and (role != UserRole.ADMIN or changes.get("is_active") is False):
            self._assert_other_active_admin(db, user)
        if "email" in changes and changes["email"]:
            clash = db.scalar(select(User).where(User.email == str(changes["email"])).where(User.id != user.id))
            if clash:
                raise DomainError("Ya existe un usuario con ese email.", status_code=409)
            user.email = str(changes["email"])
        self._validate_professional_link(db, role, professional_id, exclude_user_id=user.id)
        if changes.get("full_name"):
            user.full_name = changes["full_name"]
        if "is_active" in changes and changes["is_active"] is not None:
            user.is_active = changes["is_active"]
        user.role = role
        user.professional_id = professional_id
        create_audit_log(
            db,
            action="user.updated",
            entity_name="user",
            entity_id=str(user.id),
            actor=actor.username,
            description="User updated",
            details={key: (value.value if hasattr(value, "value") else value) for key, value in changes.items()},
        )
        db.commit()
        db.refresh(user)
        return user

    def set_password(self, db: Session, user_id: int, password: str, *, actor: User) -> User:
        user = self.get_user_by_id(db, user_id)
        if not user:
            raise DomainError("No encontramos el usuario.", status_code=404)
        if len(password) < 8:
            raise DomainError("La contraseña debe tener al menos 8 caracteres.", status_code=422)
        user.password_hash = hash_password(password)
        user.session_version += 1  # every session opened with the old password stops working
        create_audit_log(
            db,
            action="user.password_reset",
            entity_name="user",
            entity_id=str(user.id),
            actor=actor.username,
            description="Password reset",
        )
        db.commit()
        return user

    def _validate_professional_link(
        self,
        db: Session,
        role: UserRole,
        professional_id: int | None,
        *,
        exclude_user_id: int | None = None,
    ) -> None:
        if role != UserRole.PROFESSIONAL:
            return
        if not professional_id or not db.get(Professional, professional_id):
            raise DomainError("Elegí el profesional al que corresponde este usuario.", status_code=422)
        query = select(User.id).where(User.professional_id == professional_id)
        if exclude_user_id:
            query = query.where(User.id != exclude_user_id)
        if db.scalar(query):
            raise DomainError("Ese profesional ya tiene un usuario asignado.", status_code=409)

    def _assert_other_active_admin(self, db: Session, user: User) -> None:
        others = db.scalar(
            select(User.id)
            .where(User.role == UserRole.ADMIN)
            .where(User.is_active.is_(True))
            .where(User.id != user.id)
            .limit(1)
        )
        if not others:
            raise DomainError("Tiene que quedar al menos un administrador activo.", status_code=409)

    def authenticate(self, db: Session, username: str, password: str) -> User:
        user = self.get_user_by_username(db, username.strip().lower())
        if not user or not verify_password(password, user.password_hash):
            raise DomainError("Usuario o contraseña incorrectos.", status_code=401)
        if not user.is_active:
            raise DomainError("El usuario está desactivado.", status_code=403)
        return user

    def create_token_for_user(self, user: User) -> str:
        return create_access_token(
            subject=str(user.id),
            secret_key=self.settings.secret_key,
            expires_minutes=self.settings.access_token_expire_minutes,
            session_version=user.session_version,
        )

    def set_session_cookie(self, response: Response, token: str) -> None:
        response.set_cookie(
            key="access_token",
            value=f"Bearer {token}",
            httponly=True,
            samesite="lax",
            secure=self.settings.is_production,
            max_age=self.settings.access_token_expire_minutes * 60,
        )

    def get_current_user(self, db: Session, token: str) -> User:
        try:
            payload = decode_access_token(token, self.settings.secret_key)
        except Exception as exc:  # pragma: no cover - invalid tokens are tested via API behavior
            raise DomainError("La sesión expiró. Ingresá de nuevo.", status_code=401) from exc

        subject = payload.get("sub")
        if not subject:
            raise DomainError("Sesión inválida. Ingresá de nuevo.", status_code=401)
        user = self.get_user_by_id(db, int(subject))
        if not user or not user.is_active:
            raise DomainError("Usuario no disponible.", status_code=401)
        # Tokens issued before the last password change. Tokens without the claim predate it: version 0.
        if payload.get("ver", 0) != user.session_version:
            raise DomainError("La sesión expiró. Ingresá de nuevo.", status_code=401)
        return user

    def ensure_has_role(self, user: User, allowed_roles: tuple[UserRole, ...]) -> User:
        if user.role not in allowed_roles:
            raise DomainError("No tenés permisos para esta acción.", status_code=403)
        return user
