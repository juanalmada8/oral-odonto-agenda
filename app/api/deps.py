from collections.abc import Callable

from fastapi import Cookie, Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import UserRole
from app.core.exceptions import DomainError
from app.db.session import get_db
from app.integrations.email import EmailClient
from app.integrations.fake_payments import FakePaymentGateway
from app.integrations.mercadopago import MercadoPagoGateway
from app.integrations.payments import PaymentGateway
from app.integrations.whatsapp import WhatsAppClient
from app.models.user import User
from app.services.ai_agent import AIAgent
from app.services.auth_service import AuthService
from app.services.booking_agent import BookingAgent
from app.services.followup_agent import FollowUpAgent
from app.services.payment_service import PaymentService
from app.services.professional_service import ProfessionalService
from app.services.reception_agent import ReceptionAgent
from app.services.schedule_agent import ScheduleAgent
from app.services.whatsapp_bot import WhatsAppBot

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def get_reception_agent() -> ReceptionAgent:
    return ReceptionAgent()


def get_professional_service() -> ProfessionalService:
    return ProfessionalService()


def get_schedule_agent() -> ScheduleAgent:
    return ScheduleAgent(get_settings())


def get_email_client() -> EmailClient:
    return EmailClient(get_settings())


def get_whatsapp_client() -> WhatsAppClient:
    return WhatsAppClient(get_settings())


def get_followup_agent(
    email_client: EmailClient = Depends(get_email_client),
    whatsapp_client: WhatsAppClient = Depends(get_whatsapp_client),
) -> FollowUpAgent:
    return FollowUpAgent(get_settings(), email_client, whatsapp_client)


def get_payment_gateway() -> PaymentGateway | None:
    settings = get_settings()
    if settings.mercadopago_access_token:
        return MercadoPagoGateway(settings)
    if not settings.is_production:
        return FakePaymentGateway()
    return None


def get_payment_service(
    gateway: PaymentGateway | None = Depends(get_payment_gateway),
    schedule_agent: ScheduleAgent = Depends(get_schedule_agent),
    followup_agent: FollowUpAgent = Depends(get_followup_agent),
) -> PaymentService:
    return PaymentService(get_settings(), gateway, schedule_agent, followup_agent)


def get_booking_agent(
    schedule_agent: ScheduleAgent = Depends(get_schedule_agent),
    reception_agent: ReceptionAgent = Depends(get_reception_agent),
    followup_agent: FollowUpAgent = Depends(get_followup_agent),
    payment_service: PaymentService = Depends(get_payment_service),
) -> BookingAgent:
    return BookingAgent(
        get_settings(),
        schedule_agent=schedule_agent,
        reception_agent=reception_agent,
        followup_agent=followup_agent,
        payment_service=payment_service,
    )


def get_whatsapp_bot(
    whatsapp_client: WhatsAppClient = Depends(get_whatsapp_client),
    booking_agent: BookingAgent = Depends(get_booking_agent),
    schedule_agent: ScheduleAgent = Depends(get_schedule_agent),
) -> WhatsAppBot:
    return WhatsAppBot(
        get_settings(),
        whatsapp_client=whatsapp_client,
        booking_agent=booking_agent,
        schedule_agent=schedule_agent,
    )


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
        raise DomainError("Tenés que iniciar sesión.", status_code=401)
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
