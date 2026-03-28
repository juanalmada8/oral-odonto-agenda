import logging


logger = logging.getLogger(__name__)


class WhatsAppClient:
    """Future integration point for a WhatsApp provider."""

    def send_message(self, *, recipient: str, body: str) -> None:
        logger.info("WhatsApp integration placeholder for %s", recipient)
        raise NotImplementedError("WhatsApp integration is prepared but not implemented yet")
