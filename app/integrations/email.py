import logging
import smtplib
from email.message import EmailMessage

from app.core.config import Settings
from app.core.exceptions import DomainError


logger = logging.getLogger(__name__)


class EmailClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def is_configured(self) -> bool:
        return bool(self.settings.smtp_host and self.settings.email_from)

    def send_email(self, *, recipient: str, subject: str, body: str) -> None:
        if not self.is_configured():
            raise DomainError("SMTP is not configured for outbound email", status_code=503)

        message = EmailMessage()
        message["From"] = self.settings.email_from
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(body)

        logger.info("Sending email notification to %s", recipient)
        with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port) as smtp:
            if self.settings.smtp_use_tls:
                smtp.starttls()
            if self.settings.smtp_username and self.settings.smtp_password:
                smtp.login(self.settings.smtp_username, self.settings.smtp_password)
            smtp.send_message(message)
