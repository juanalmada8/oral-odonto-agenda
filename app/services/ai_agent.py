"""Optional AI agent for natural-language helpers, decoupled from core business rules."""

from typing import Any

from app.core.config import Settings


class AIAgent:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def is_enabled(self) -> bool:
        return bool(self.settings.openai_api_key)

    def interpret_patient_message(self, message: str) -> dict[str, Any]:
        if not self.is_enabled():
            return {
                "enabled": False,
                "source": "fallback",
                "intent": "unknown",
                "summary": message[:140],
                "reply_suggestion": "Recibimos tu mensaje. En breve te ayudamos con tu turno.",
            }

        try:
            from openai import OpenAI
        except ImportError:
            return {
                "enabled": False,
                "source": "missing_sdk",
                "intent": "unknown",
                "summary": message[:140],
                "reply_suggestion": "Recibimos tu mensaje. En breve te ayudamos con tu turno.",
            }

        client = OpenAI(api_key=self.settings.openai_api_key)
        response = client.responses.create(
            model=self.settings.openai_model,
            input=(
                "Extract intent and write a short friendly reply for a dental clinic message. "
                f"Message: {message}"
            ),
        )
        return {
            "enabled": True,
            "source": "openai",
            "raw_response": response.output_text,
        }
