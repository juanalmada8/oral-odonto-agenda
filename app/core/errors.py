"""Turn exceptions into messages that are safe and useful to show on the web UI."""

import logging

from pydantic import ValidationError

from app.core.exceptions import DomainError

logger = logging.getLogger(__name__)

GENERIC_ERROR_MESSAGE = "Tuvimos un problema al procesar la solicitud. Intentá de nuevo en unos minutos."

FIELD_LABELS = {
    "dni": "DNI",
    "first_name": "Nombre",
    "last_name": "Apellido",
    "email": "Email",
    "phone": "Celular",
    "starts_at": "Horario",
    "professional_id": "Profesional",
    "reason": "Motivo",
    "observations": "Observaciones",
    "notes": "Notas",
    "duration_minutes": "Duración",
    "default_appointment_duration": "Duración por defecto",
    "slot_duration_minutes": "Duración del turno",
    "deposit_amount": "Seña",
    "availability_date": "Fecha",
    "start_time": "Hora de inicio",
    "end_time": "Hora de fin",
    "username": "Usuario",
    "password": "Contraseña",
    "full_name": "Nombre completo",
    "specialty": "Especialidad",
}


def humanize_validation_error(exc: ValidationError) -> str:
    """First validation problem, phrased for a patient ("Email: ingresá un email válido.")."""
    error = exc.errors()[0]
    field = str(error["loc"][-1]) if error.get("loc") else ""
    label = FIELD_LABELS.get(field, field.replace("_", " ").capitalize())
    error_type = error.get("type", "")
    context = error.get("ctx") or {}

    if field == "email":
        return "Email: ingresá un email válido (ej: nombre@correo.com)."
    if error_type == "value_error":
        # Our validators raise complete Spanish sentences; show them untouched.
        return str(context.get("error") or error.get("msg", "")).removeprefix("Value error, ")
    if error_type == "missing":
        return f"{label}: es un dato obligatorio."
    if error_type == "string_too_short":
        return f"{label}: debe tener al menos {context.get('min_length')} caracteres."
    if error_type == "string_too_long":
        return f"{label}: no puede superar los {context.get('max_length')} caracteres."
    if error_type in {"greater_than_equal", "greater_than"}:
        return f"{label}: el valor es demasiado bajo."
    if error_type in {"less_than_equal", "less_than"}:
        return f"{label}: el valor es demasiado alto."
    if error_type.startswith(("datetime", "date", "time")):
        return f"{label}: elegí una fecha u horario válido."
    if error_type.startswith(("int", "float", "decimal")):
        return f"{label}: ingresá un número válido."
    return f"{label}: el valor no es válido."


def user_facing_message(exc: Exception) -> str:
    """Message for flash banners. Unexpected errors are logged and never leaked."""
    if isinstance(exc, DomainError):
        return exc.detail
    if isinstance(exc, ValidationError):
        return humanize_validation_error(exc)
    logger.exception("Unexpected error while handling a web form", exc_info=exc)
    return GENERIC_ERROR_MESSAGE
