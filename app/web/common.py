"""Shared helpers for server-rendered pages: templates, filters, flash redirects."""

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlencode

from fastapi import Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import APPOINTMENT_STATUS_LABELS, PAYMENT_STATUS_LABELS, AppointmentStatus, PaymentStatus, UserRole
from app.core.exceptions import DomainError
from app.models.user import User
from app.services.professional_service import ProfessionalService
from app.utils.validation import format_phone_for_display

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)

DAY_LABELS = {
    0: "Lunes",
    1: "Martes",
    2: "Miércoles",
    3: "Jueves",
    4: "Viernes",
    5: "Sábado",
    6: "Domingo",
}
MONTH_LABELS = {
    1: "enero",
    2: "febrero",
    3: "marzo",
    4: "abril",
    5: "mayo",
    6: "junio",
    7: "julio",
    8: "agosto",
    9: "septiembre",
    10: "octubre",
    11: "noviembre",
    12: "diciembre",
}


def format_money(value: Decimal | int | float | None) -> str:
    """Argentine format: $ 12.500 (cents only when present)."""
    if value is None:
        return ""
    amount = Decimal(value).quantize(Decimal("0.01"))
    integer, _, cents = f"{amount:,.2f}".partition(".")
    integer = integer.replace(",", ".")
    return f"$ {integer}" if cents == "00" else f"$ {integer},{cents}"


def format_long_date(value: date | datetime | None) -> str:
    """'martes 31 de marzo'."""
    if value is None:
        return ""
    return f"{DAY_LABELS[value.weekday()].lower()} {value.day} de {MONTH_LABELS[value.month]}"


def format_short_date(value: date | datetime | None) -> str:
    """'Mar 31/03'."""
    if value is None:
        return ""
    return f"{DAY_LABELS[value.weekday()][:3]} {value:%d/%m}"


def mask_email(value: str | None) -> str:
    if not value or "@" not in value:
        return value or ""
    local, domain = value.split("@", 1)
    return f"{local[:1]}{'•' * max(1, min(len(local) - 1, 4))}@{domain}"


def status_label(status: AppointmentStatus | PaymentStatus | str | None) -> str:
    if isinstance(status, AppointmentStatus):
        return APPOINTMENT_STATUS_LABELS[status]
    if isinstance(status, PaymentStatus):
        return PAYMENT_STATUS_LABELS[status]
    return str(status or "")


templates.env.filters["money"] = format_money
templates.env.filters["long_date"] = format_long_date
templates.env.filters["short_date"] = format_short_date
templates.env.filters["mask_email"] = mask_email
templates.env.filters["status_label"] = status_label
templates.env.filters["phone"] = format_phone_for_display
templates.env.globals["settings"] = get_settings()


def redirect_with_message(
    path: str,
    *,
    message: str | None = None,
    error: str | None = None,
    fragment: str | None = None,
) -> RedirectResponse:
    params: dict[str, str] = {}
    if message:
        params["message"] = message
    if error:
        params["error"] = error
    separator = "&" if "?" in path else "?"
    target = f"{path}{separator}{urlencode(params)}" if params else path
    if fragment:
        target = f"{target}#{fragment}"
    return RedirectResponse(url=target, status_code=303)


def render_admin(
    request: Request,
    *,
    template_name: str,
    current_user: User,
    page_title: str,
    page_subtitle: str,
    active_page: str,
    **context,
):
    return templates.TemplateResponse(
        request,
        template_name,
        {
            "current_user": current_user,
            "page_title": page_title,
            "page_subtitle": page_subtitle,
            "active_page": active_page,
            "message": request.query_params.get("message"),
            "error": request.query_params.get("error"),
            "day_labels": DAY_LABELS,
            **context,
        },
    )


def ensure_admin(current_user: User) -> None:
    if current_user.role != UserRole.ADMIN:
        raise DomainError("Solo admin puede acceder a esta sección", status_code=403)


def active_professionals(db: Session, professional_service: ProfessionalService):
    return [professional for professional in professional_service.list_professionals(db) if professional.is_active]


def serialize_status_counts(appointments: list) -> dict[str, int]:
    counts = {status.value: 0 for status in AppointmentStatus}
    for appointment in appointments:
        counts[appointment.status.value] += 1
    return counts


def filter_patients_collection(patients: list, query: str | None):
    if not query:
        return patients
    normalized = query.strip().lower()
    return [
        patient
        for patient in patients
        if normalized in patient.first_name.lower()
        or normalized in patient.last_name.lower()
        or normalized in patient.dni.lower()
    ]
