from collections.abc import Callable

from fastapi import Cookie, Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import UserRole
from app.core.exceptions import DomainError
from app.db.session import get_db
from app.integrations.email import EmailClient
from app.models.user import User
from app.services.ai_agent import AIAgent
from app.services.auth_service import AuthService
from app.services.followup_agent import FollowUpAgent
from app.services.professional_service import ProfessionalService
from app.services.reception_agent import ReceptionAgent
from app.services.schedule_agent import ScheduleAgent

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def get_reception_agent() -> ReceptionAgent:
    return ReceptionAgent()


def get_professional_service() -> ProfessionalService:
    return ProfessionalService()


def get_schedule_agent() -> ScheduleAgent:
    settings = get_settings()
    return ScheduleAgent(timezone_name=settings.app_timezone)


def get_followup_agent() -> FollowUpAgent:
    settings = get_settings()
    return FollowUpAgent(settings=settings, email_client=EmailClient(settings))


def get_ai_agent() -> AIAgent:
    return AIAgent(get_settings())


def get_auth_service() -> AuthService:
    return AuthService(get_settings())


def get_current_user(
    db: Session = Depends(get_db),
    header_token: str | None = Depends(oauth2_scheme),
    cookie_token: str | None = Cookie(default=None, alias="access_token"),
    auth_service: AuthService = Depends(get_auth_service),
) -> User:
    raw_token = header_token or cookie_token
    if not raw_token:
        raise DomainError("Not authenticated", status_code=401)
    if raw_token.startswith("Bearer "):
        raw_token = raw_token.removeprefix("Bearer ").strip()
    return auth_service.get_current_user(db, raw_token)


def require_roles(*roles: UserRole) -> Callable:
    def dependency(
        current_user: User = Depends(get_current_user),
        auth_service: AuthService = Depends(get_auth_service),
    ) -> User:
        return auth_service.ensure_has_role(current_user, roles)

    return dependency
