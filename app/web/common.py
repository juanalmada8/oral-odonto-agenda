"""Shared helpers for server-rendered pages: templates, filters, flash redirects."""

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
from app.utils.formatting import DAY_LABELS, format_long_date, format_money, format_short_date, mask_email
from app.utils.validation import format_phone_for_display

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)


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
