"""Links that let a patient confirm one specific appointment time (spec 0005).

The code is an HMAC of the appointment's public token and its start time, keyed with the app's
SECRET_KEY. Nothing is stored: moving the appointment changes its start time, so every link sent
for the old time stops working on its own and only the new email can confirm the new time.
"""

import base64
import hashlib
import hmac

from app.models.appointment import Appointment


def confirmation_code(secret_key: str, appointment: Appointment) -> str:
    message = f"confirm|{appointment.public_token}|{appointment.starts_at.isoformat()}".encode()
    digest = hmac.new(secret_key.encode(), message, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest[:18]).decode().rstrip("=")


def is_valid_confirmation_code(secret_key: str, appointment: Appointment, code: str | None) -> bool:
    if not code:
        return False
    return hmac.compare_digest(confirmation_code(secret_key, appointment), code)


def confirmation_path(secret_key: str, appointment: Appointment) -> str:
    return f"/reservar/turno/{appointment.public_token}/confirmar?c={confirmation_code(secret_key, appointment)}"
