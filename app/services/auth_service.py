from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.enums import UserRole
from app.core.exceptions import DomainError
from app.core.security import create_access_token, decode_access_token, hash_password, verify_password
from app.models.user import User
from app.schemas.auth import UserCreate
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
            raise DomainError("A user already exists with the same username or email", status_code=409)
        user = User(
            username=payload.username,
            full_name=payload.full_name,
            email=str(payload.email),
            password_hash=hash_password(payload.password),
            role=payload.role,
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

    def authenticate(self, db: Session, username: str, password: str) -> User:
        user = self.get_user_by_username(db, username)
        if not user or not verify_password(password, user.password_hash):
            raise DomainError("Invalid credentials", status_code=401)
        if not user.is_active:
            raise DomainError("User is inactive", status_code=403)
        return user

    def create_token_for_user(self, user: User) -> str:
        return create_access_token(
            subject=str(user.id),
            secret_key=self.settings.secret_key,
            expires_minutes=self.settings.access_token_expire_minutes,
        )

    def get_current_user(self, db: Session, token: str) -> User:
        try:
            payload = decode_access_token(token, self.settings.secret_key)
        except Exception as exc:  # pragma: no cover - invalid tokens are tested via API behavior
            raise DomainError("Invalid or expired token", status_code=401) from exc

        subject = payload.get("sub")
        if not subject:
            raise DomainError("Invalid token payload", status_code=401)
        user = self.get_user_by_id(db, int(subject))
        if not user or not user.is_active:
            raise DomainError("User not available", status_code=401)
        return user

    def ensure_has_role(self, user: User, allowed_roles: tuple[UserRole, ...]) -> User:
        if user.role not in allowed_roles:
            raise DomainError("You do not have permission for this action", status_code=403)
        return user
