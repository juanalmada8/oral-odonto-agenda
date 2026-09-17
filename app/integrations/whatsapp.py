"""WhatsApp Cloud API client (Meta Graph API).

Docs: https://developers.facebook.com/docs/whatsapp/cloud-api
Business-initiated messages (reminders) must use an approved template; free-form text and
interactive buttons are only allowed within 24 hours of the patient's last message.
"""

import hashlib
import hmac
import logging

import httpx

from app.core.config import Settings

logger = logging.getLogger(__name__)

GRAPH_BASE_URL = "https://graph.facebook.com"


class WhatsAppError(Exception):
    """The Cloud API rejected the message or could not be reached."""


def whatsapp_recipient(phone_e164: str) -> str:
    return "".join(char for char in phone_e164 if char.isdigit())


def same_whatsapp_number(first: str | None, second: str | None) -> bool:
    """Compare numbers ignoring formatting and Argentina's optional mobile "9" (54 9 11... vs 54 11...)."""

    def canonical(value: str | None) -> str:
        digits = whatsapp_recipient(value or "")
        return "54" + digits[3:] if digits.startswith("549") else digits

    return bool(first and second) and canonical(first) == canonical(second)


def verify_meta_signature(*, app_secret: str, raw_body: bytes, signature_header: str | None) -> bool:
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header.removeprefix("sha256="))


class WhatsAppClient:
    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self.settings = settings
        self._client = client or httpx.Client(base_url=GRAPH_BASE_URL, timeout=httpx.Timeout(15.0, connect=5.0))

    def is_configured(self) -> bool:
        return bool(self.settings.whatsapp_access_token and self.settings.whatsapp_phone_number_id)

    def send_template(
        self,
        *,
        to: str,
        template: str,
        language: str,
        body_params: list[str],
        button_payloads: list[str] | None = None,
    ) -> str:
        components: list[dict] = [
            {"type": "body", "parameters": [{"type": "text", "text": value} for value in body_params]}
        ]
        for index, payload in enumerate(button_payloads or []):
            components.append(
                {
                    "type": "button",
                    "sub_type": "quick_reply",
                    "index": str(index),
                    "parameters": [{"type": "payload", "payload": payload}],
                }
            )
        return self._send(
            to,
            {
                "type": "template",
                "template": {"name": template, "language": {"code": language}, "components": components},
            },
        )

    def send_text(self, *, to: str, body: str) -> str:
        return self._send(to, {"type": "text", "text": {"preview_url": False, "body": body}})

    def send_buttons(self, *, to: str, body: str, buttons: list[tuple[str, str]]) -> str:
        """Interactive reply buttons: [(id, title)], max 3, titles up to 20 characters."""
        return self._send(
            to,
            {
                "type": "interactive",
                "interactive": {
                    "type": "button",
                    "body": {"text": body},
                    "action": {
                        "buttons": [
                            {"type": "reply", "reply": {"id": button_id, "title": title[:20]}}
                            for button_id, title in buttons[:3]
                        ]
                    },
                },
            },
        )

    def verify_signature(self, raw_body: bytes, signature_header: str | None) -> bool:
        secret = self.settings.whatsapp_app_secret
        if not secret:
            logger.warning("WHATSAPP_APP_SECRET not set: accepting unsigned WhatsApp webhook")
            return not self.settings.is_production
        return verify_meta_signature(app_secret=secret, raw_body=raw_body, signature_header=signature_header)

    def _send(self, to: str, message: dict) -> str:
        if not self.is_configured():
            raise WhatsAppError("WhatsApp Cloud API is not configured")
        url = f"/{self.settings.whatsapp_api_version}/{self.settings.whatsapp_phone_number_id}/messages"
        body = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": whatsapp_recipient(to), **message}
        try:
            response = self._client.post(
                url,
                json=body,
                headers={"Authorization": f"Bearer {self.settings.whatsapp_access_token}"},
            )
        except httpx.HTTPError as exc:
            raise WhatsAppError(f"WhatsApp unreachable: {exc}") from exc
        if response.status_code >= 400:
            try:
                error = response.json().get("error", {})
                detail = f"{error.get('code')}: {error.get('message')}"
            except ValueError:
                detail = response.text[:300]
            raise WhatsAppError(f"WhatsApp rejected the message ({response.status_code}) {detail}")
        return response.json()["messages"][0]["id"]
