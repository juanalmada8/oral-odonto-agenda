"""Patient-facing pages: online booking, booking status and the local payment simulator."""

import logging
from datetime import UTC, date, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app.api.deps import (
    get_booking_agent,
    get_followup_agent,
    get_payment_service,
    get_professional_service,
    get_schedule_agent,
)
from app.core import clock
from app.core.config import get_settings
from app.core.enums import AppointmentStatus, PaymentStatus
from app.core.errors import user_facing_message
from app.core.exceptions import DomainError
from app.core.rate_limit import client_ip, rate_limiter
from app.db.session import get_db
from app.integrations.fake_payments import FakePaymentGateway
from app.integrations.payments import PaymentGatewayError, PaymentInfo
from app.models.appointment import Appointment
from app.schemas.booking import PublicBookingRequest
from app.services.booking_agent import BookingAgent
from app.services.followup_agent import FollowUpAgent
from app.services.payment_service import PaymentService, hold_seconds_left
from app.services.professional_service import ProfessionalService
from app.services.schedule_agent import ScheduleAgent
from app.tasks.notifications import dispatch_due_notifications
from app.web.common import active_professionals, format_long_date, format_short_date, redirect_with_message, templates

logger = logging.getLogger(__name__)
router = APIRouter(include_in_schema=False)

def _parse_int(value: str | None) -> int | None:
    try:
        return int(value) if value else None
    except ValueError:
        return None


def _parse_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def booking_page_context(
    db: Session,
    *,
    professional_service: ProfessionalService,
    schedule_agent: ScheduleAgent,
    payment_service: PaymentService,
    professional_id: int | None,
    selected_date: date | None,
) -> dict:
    professionals = active_professionals(db, professional_service)
    selected_professional = next((item for item in professionals if item.id == professional_id), None)
    available_dates: list[dict] = []
    available_slots = []
    agenda_date = selected_date

    if selected_professional:
        earliest_start, last_date = schedule_agent.public_booking_bounds()
        dates = schedule_agent.list_available_dates(
            db,
            professional_id=selected_professional.id,
            date_from=earliest_start.date(),
            date_to=last_date,
            earliest_start=earliest_start,
            limit=30,
        )
        available_dates = [
            {
                "value": day.isoformat(),
                "label": format_short_date(day),
                "long_label": format_long_date(day),
                "slots": count,
            }
            for day, count in dates
        ]
        values = {item["value"] for item in available_dates}
        if available_dates and (agenda_date is None or agenda_date.isoformat() not in values):
            agenda_date = date.fromisoformat(available_dates[0]["value"])
        if agenda_date and agenda_date.isoformat() in values:
            available_slots = schedule_agent.get_daily_availability(
                db,
                professional_id=selected_professional.id,
                day=agenda_date,
                earliest_start=earliest_start,
            )

    deposit = payment_service.deposit_for(selected_professional) if selected_professional else None
    return {
        "professionals": professionals,
        "selected_professional": selected_professional,
        "selected_date": agenda_date.isoformat() if agenda_date else "",
        "selected_date_label": format_long_date(agenda_date) if agenda_date else "",
        "available_dates": available_dates,
        "available_slots": available_slots,
        "deposit_amount": deposit if deposit and deposit > 0 else None,
        "hold_minutes": get_settings().booking_hold_minutes,
    }


@router.get("/reservar", response_class=HTMLResponse)
def public_booking_page(
    request: Request,
    professional_id: str | None = None,
    selected_date: str | None = None,
    db: Session = Depends(get_db),
    professional_service: ProfessionalService = Depends(get_professional_service),
    schedule_agent: ScheduleAgent = Depends(get_schedule_agent),
    payment_service: PaymentService = Depends(get_payment_service),
):
    context = booking_page_context(
        db,
        professional_service=professional_service,
        schedule_agent=schedule_agent,
        payment_service=payment_service,
        professional_id=_parse_int(professional_id),
        selected_date=_parse_date(selected_date),
    )
    return templates.TemplateResponse(
        request,
        "public_booking.html",
        {**context, "form": {}, "message": request.query_params.get("message"), "error": request.query_params.get("error")},
    )


@router.post("/reservar", response_class=HTMLResponse)
def create_public_booking(
    request: Request,
    professional_id: str = Form(""),
    starts_at: str = Form(""),
    dni: str = Form(""),
    first_name: str = Form(""),
    last_name: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    reason: str = Form(""),
    observations: str = Form(""),
    accept_terms: str = Form(""),
    website: str = Form(""),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: Session = Depends(get_db),
    professional_service: ProfessionalService = Depends(get_professional_service),
    schedule_agent: ScheduleAgent = Depends(get_schedule_agent),
    payment_service: PaymentService = Depends(get_payment_service),
    booking_agent: BookingAgent = Depends(get_booking_agent),
    followup_agent: FollowUpAgent = Depends(get_followup_agent),
):
    form = {
        "dni": dni,
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "phone": phone,
        "reason": reason,
        "observations": observations,
        "starts_at": starts_at,
        "accept_terms": bool(accept_terms),
    }

    def render_error(message: str):
        selected_day = None
        try:
            selected_day = datetime.fromisoformat(starts_at).date() if starts_at else None
        except ValueError:
            pass
        context = booking_page_context(
            db,
            professional_service=professional_service,
            schedule_agent=schedule_agent,
            payment_service=payment_service,
            professional_id=_parse_int(professional_id),
            selected_date=selected_day,
        )
        return templates.TemplateResponse(
            request,
            "public_booking.html",
            {**context, "form": form, "error": message, "message": None},
            status_code=422,
        )

    settings = get_settings()
    if website:
        # Honeypot field, invisible to people: only bots fill it.
        logger.info("Booking honeypot triggered from %s", client_ip(request))
        return render_error("No pudimos procesar la reserva. Intentá de nuevo.")
    if not rate_limiter.allow(
        f"booking:{client_ip(request)}", limit=settings.booking_rate_limit_per_hour, window_seconds=3600
    ):
        return render_error("Hiciste muchos intentos seguidos. Esperá unos minutos y volvé a intentar.")

    try:
        booking_request = PublicBookingRequest(
            professional_id=_parse_int(professional_id) or 0,
            starts_at=starts_at or None,
            dni=dni,
            first_name=first_name,
            last_name=last_name,
            email=email.strip(),
            phone=phone,
            reason=reason,
            observations=observations,
            accept_terms=bool(accept_terms),
        )
        result = booking_agent.book(db, booking_request)
    except Exception as exc:
        db.rollback()
        return render_error(user_facing_message(exc))

    background_tasks.add_task(dispatch_due_notifications, followup_agent)
    status_url = f"/reservar/turno/{result.appointment.public_token}"
    if result.checkout_url:
        return RedirectResponse(result.checkout_url, status_code=303)
    if result.checkout_error:
        return redirect_with_message(status_url, error=result.checkout_error)
    return RedirectResponse(status_url, status_code=303)


def _booking_view(appointment: Appointment, payment_service: PaymentService, booking_agent: BookingAgent) -> dict:
    payment = appointment.latest_payment
    return {
        "can_cancel": booking_agent.can_cancel_online(appointment),
        "is_upcoming": appointment.status in {AppointmentStatus.RESERVED, AppointmentStatus.CONFIRMED},
        "appointment": appointment,
        "payment": payment,
        "seconds_left": hold_seconds_left(appointment),
        "can_pay": (
            appointment.status == AppointmentStatus.PENDING_PAYMENT
            and hold_seconds_left(appointment) > 0
            and (payment is None or payment.status in {PaymentStatus.PENDING, PaymentStatus.REJECTED})
        ),
        "payment_rejected": bool(payment and payment.status == PaymentStatus.REJECTED),
        "requires_refund": bool(payment and payment_service.requires_refund(payment)),
        "can_add_to_calendar": appointment.status in {AppointmentStatus.CONFIRMED, AppointmentStatus.RESERVED},
    }


@router.get("/reservar/turno/{public_token}", response_class=HTMLResponse)
def booking_status_page(
    request: Request,
    public_token: str,
    payment_id: str | None = None,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: Session = Depends(get_db),
    schedule_agent: ScheduleAgent = Depends(get_schedule_agent),
    payment_service: PaymentService = Depends(get_payment_service),
    booking_agent: BookingAgent = Depends(get_booking_agent),
    followup_agent: FollowUpAgent = Depends(get_followup_agent),
):
    appointment = _get_public_appointment(db, schedule_agent, public_token)
    if appointment is None:
        return templates.TemplateResponse(request, "public_booking_missing.html", {}, status_code=404)

    if payment_id and not isinstance(payment_service.gateway, FakePaymentGateway):
        # Back from Mercado Pago: don't wait for the webhook, ask the API right away.
        try:
            payment_service.sync_provider_payment(db, payment_id)
        except (DomainError, PaymentGatewayError) as exc:
            db.rollback()
            logger.warning("Could not sync payment %s on return: %s", payment_id, exc)
        background_tasks.add_task(dispatch_due_notifications, followup_agent)
        return RedirectResponse(f"/reservar/turno/{public_token}", status_code=303)

    payment_service.expire_unpaid(db)
    db.refresh(appointment)
    return templates.TemplateResponse(
        request,
        "public_booking_status.html",
        {
            **_booking_view(appointment, payment_service, booking_agent),
            "message": request.query_params.get("message"),
            "error": request.query_params.get("error"),
        },
    )


@router.get("/reservar/turno/{public_token}/estado")
def booking_status_json(
    public_token: str,
    db: Session = Depends(get_db),
    schedule_agent: ScheduleAgent = Depends(get_schedule_agent),
):
    appointment = _get_public_appointment(db, schedule_agent, public_token)
    if appointment is None:
        return JSONResponse({"detail": "not found"}, status_code=404)
    payment = appointment.latest_payment
    return {
        "status": appointment.status.value,
        "payment_status": payment.status.value if payment else None,
        "seconds_left": hold_seconds_left(appointment),
    }


@router.post("/reservar/turno/{public_token}/pagar")
def retry_booking_payment(
    public_token: str,
    db: Session = Depends(get_db),
    schedule_agent: ScheduleAgent = Depends(get_schedule_agent),
    booking_agent: BookingAgent = Depends(get_booking_agent),
):
    status_url = f"/reservar/turno/{public_token}"
    appointment = _get_public_appointment(db, schedule_agent, public_token)
    if appointment is None:
        return RedirectResponse("/reservar", status_code=303)
    try:
        result = booking_agent.retry_checkout(db, appointment)
    except DomainError as exc:
        db.rollback()
        return redirect_with_message(status_url, error=exc.detail)
    if result.checkout_url:
        return RedirectResponse(result.checkout_url, status_code=303)
    return redirect_with_message(status_url, error=result.checkout_error or "No pudimos generar el link de pago.")


@router.post("/reservar/turno/{public_token}/cancelar")
def cancel_booking_by_patient(
    public_token: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    schedule_agent: ScheduleAgent = Depends(get_schedule_agent),
    booking_agent: BookingAgent = Depends(get_booking_agent),
    followup_agent: FollowUpAgent = Depends(get_followup_agent),
):
    status_url = f"/reservar/turno/{public_token}"
    appointment = _get_public_appointment(db, schedule_agent, public_token)
    if appointment is None:
        return RedirectResponse("/reservar", status_code=303)
    try:
        booking_agent.cancel_by_patient(db, appointment, channel="link")
    except DomainError as exc:
        db.rollback()
        return redirect_with_message(status_url, error=exc.detail)
    background_tasks.add_task(dispatch_due_notifications, followup_agent)
    return redirect_with_message(status_url, message="Cancelamos tu turno. Te enviamos la confirmación por email.")


@router.get("/reservar/turno/{public_token}/calendario.ics")
def booking_calendar_file(
    public_token: str,
    db: Session = Depends(get_db),
    schedule_agent: ScheduleAgent = Depends(get_schedule_agent),
):
    appointment = _get_public_appointment(db, schedule_agent, public_token)
    if appointment is None or appointment.status not in {AppointmentStatus.CONFIRMED, AppointmentStatus.RESERVED}:
        return Response(status_code=404)
    return Response(
        content=build_ics(appointment),
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="turno-oral.ics"'},
    )


def build_ics(appointment: Appointment) -> str:
    settings = get_settings()

    def utc(value: datetime) -> str:
        return clock.to_aware(value).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")

    def escape(value: str) -> str:
        return value.replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")

    professional = f"{appointment.professional.first_name} {appointment.professional.last_name}"
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//ORAL//Turnos//ES",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{appointment.public_token}@oral-turnos",
        f"DTSTAMP:{datetime.now(UTC):%Y%m%dT%H%M%SZ}",
        f"DTSTART:{utc(appointment.starts_at)}",
        f"DTEND:{utc(appointment.ends_at)}",
        f"SUMMARY:{escape(f'Turno odontológico · {professional}')}",
        f"DESCRIPTION:{escape(f'{settings.clinic_name}. Ver turno: {settings.public_base_url}/reservar/turno/{appointment.public_token}')}",
    ]
    if settings.clinic_address:
        lines.append(f"LOCATION:{escape(settings.clinic_address)}")
    lines += ["END:VEVENT", "END:VCALENDAR", ""]
    return "\r\n".join(lines)


def _get_public_appointment(db: Session, schedule_agent: ScheduleAgent, public_token: str) -> Appointment | None:
    if len(public_token) > 64:
        return None
    try:
        return schedule_agent.get_appointment_by_token(db, public_token)
    except DomainError:
        return None


# ------------------------------------------------------------------ simulator


def _simulator_enabled(payment_service: PaymentService) -> bool:
    return isinstance(payment_service.gateway, FakePaymentGateway) and not get_settings().is_production


@router.get("/pagos/simulador/{reference}", response_class=HTMLResponse)
def payment_simulator_page(
    request: Request,
    reference: str,
    db: Session = Depends(get_db),
    payment_service: PaymentService = Depends(get_payment_service),
):
    if not _simulator_enabled(payment_service):
        return Response(status_code=404)
    try:
        payment = payment_service.get_by_reference(db, reference)
    except DomainError:
        return Response(status_code=404)
    return templates.TemplateResponse(request, "payment_simulator.html", {"payment": payment})


@router.post("/pagos/simulador/{reference}")
def payment_simulator_submit(
    reference: str,
    background_tasks: BackgroundTasks,
    decision: str = Form(...),
    db: Session = Depends(get_db),
    payment_service: PaymentService = Depends(get_payment_service),
    followup_agent: FollowUpAgent = Depends(get_followup_agent),
):
    if not _simulator_enabled(payment_service):
        return Response(status_code=404)
    try:
        payment = payment_service.get_by_reference(db, reference)
        token = payment.appointment.public_token
        approved = decision == "approve"
        payment_service.apply_payment_info(
            db,
            PaymentInfo(
                provider_payment_id=f"sim-{reference[:12]}-{int(datetime.now(UTC).timestamp())}",
                status=PaymentStatus.APPROVED if approved else PaymentStatus.REJECTED,
                status_detail="accredited" if approved else "cc_rejected_other_reason",
                external_reference=reference,
                amount=payment.amount,
                currency=payment.currency,
                paid_at=clock.now() if approved else None,
            ),
        )
    except DomainError:
        db.rollback()
        return Response(status_code=404)
    background_tasks.add_task(dispatch_due_notifications, followup_agent)
    return RedirectResponse(f"/reservar/turno/{token}", status_code=303)
