import logging
import smtplib
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from pathlib import Path

from app.core.config import Settings
from app.core.exceptions import DomainError


logger = logging.getLogger(__name__)

# The logo travels inside the message instead of as a link: Gmail and Outlook block remote
# images by default, and a link would also need the site to be reachable from the reader's network.
LOGO_CID = "oral-logo"
# 420px wide: the email renders it at 180, so this covers retina without carrying the print-size file.
LOGO_PATH = Path(__file__).resolve().parents[1] / "static" / "brand" / "oral-logo-email.png"


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
            self._attach_logo(message)

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

    def _attach_logo(self, message: EmailMessage) -> None:
        """Embed the logo in the HTML part so it shows without the reader allowing remote images."""
        if not LOGO_PATH.exists():
            logger.warning("Brand logo not found at %s; the email goes out without it", LOGO_PATH)
            return
        html_part = message.get_payload()[-1]
        html_part.add_related(
            LOGO_PATH.read_bytes(),
            maintype="image",
            subtype="png",
            cid=f"<{LOGO_CID}>",
            filename="oral.png",
        )
