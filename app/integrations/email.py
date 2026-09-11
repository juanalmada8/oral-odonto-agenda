import logging
import smtplib
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from app.core.config import Settings
from app.core.exceptions import DomainError


logger = logging.getLogger(__name__)


class EmailClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def is_configured(self) -> bool:
        return bool(self.settings.smtp_host and self.settings.email_from)

    def send_email(self, *, recipient: str, subject: str, body: str, html: str | None = None) -> str:
        """Send a text email (plus an HTML alternative when given). Returns the Message-ID."""
        if not self.is_configured():
            raise DomainError("SMTP is not configured for outbound email", status_code=503)

        message = EmailMessage()
        message["From"] = formataddr((self.settings.clinic_name, self.settings.email_from))
        message["To"] = recipient
        message["Subject"] = subject
        message["Message-ID"] = make_msgid(domain=self.settings.email_from.split("@")[-1])
        message.set_content(body)
        if html:
            message.add_alternative(html, subtype="html")

        logger.info("Sending email notification to %s", recipient)
        port = self.settings.smtp_port
        smtp_class = smtplib.SMTP_SSL if port == 465 else smtplib.SMTP
        with smtp_class(self.settings.smtp_host, port, timeout=20) as smtp:
            if self.settings.smtp_use_tls and smtp_class is smtplib.SMTP:
                smtp.starttls()
            if self.settings.smtp_username and self.settings.smtp_password:
                smtp.login(self.settings.smtp_username, self.settings.smtp_password)
            smtp.send_message(message)
        return message["Message-ID"]
