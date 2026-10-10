"""Internal panel (/app): reception and admin run the clinic; professionals manage their own agenda."""

from collections import defaultdict
from datetime import date, datetime, timedelta
from itertools import groupby
from urllib.parse import urlencode

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import (
    get_auth_service,
    get_current_user,
    get_followup_service,
    get_payment_service,
    get_professional_service,
    get_reception_service,
    get_schedule_service,
)
from app.core import clock
from app.core.enums import (
    NOTIFICATION_TYPE_LABELS,
    ROLE_LABELS,
    WAITLIST_PERIOD_LABELS,
    WAITLIST_STATUS_LABELS,
    AppointmentStatus,
    NotificationChannel,
    NotificationStatus,
    UserRole,
    WaitlistStatus,
)
from app.core.errors import user_facing_message
from app.core.exceptions import DomainError
from app.core.rate_limit import enforce_login_rate_limit
from app.db.session import get_db
from app.models.notification import Notification
from app.models.user import User
from app.schemas.appointment import AppointmentCreate, AppointmentSeriesCreate, AppointmentUpdate
from app.schemas.auth import UserCreate, UserUpdate
from app.schemas.availability import AvailabilityWindowCreate, RecurringAvailabilityCreate
from app.schemas.patient import PatientCreate, PatientUpdate
from app.schemas.professional import ProfessionalCreate, ProfessionalUpdate
from app.services.analytics import AnalyticsService
from app.services.auth_service import AuthService
from app.services.followup_service import FollowUpService
from app.services.payment_service import PaymentService
from app.services.professional_service import ProfessionalService
from app.services.reception_service import ReceptionService
from app.services.schedule_service import ALLOWED_TRANSITIONS, ScheduleService
from app.services.waitlist_service import WaitlistService
from app.tasks.notifications import dispatch_due_notifications
from app.utils.formatting import format_money
from app.utils.validation import parse_money
from app.web.common import (
    active_professionals,
    filter_patients_collection,
    format_long_date,
    format_short_date,
    redirect_with_message,
    render_admin,
    serialize_status_counts,
    templates,
)

router = APIRouter(include_in_schema=False)

STAFF = (UserRole.ADMIN, UserRole.RECEPTIONIST)
ADMIN_ONLY = (UserRole.ADMIN,)
# What each role may do from the agenda table.
STAFF_ACTIONS = {"confirm", "reserve", "complete", "no_show", "cancel"}
PROFESSIONAL_ACTIONS = {"complete", "no_show"}
# Appointments still ahead that the clinic has to attend.
UPCOMING_STATUSES = (AppointmentStatus.PENDING_PAYMENT, AppointmentStatus.RESERVED, AppointmentStatus.CONFIRMED)

ACTION_TARGETS = {
    "confirm": AppointmentStatus.CONFIRMED,
    "reserve": AppointmentStatus.RESERVED,
    "complete": AppointmentStatus.COMPLETED,
    "no_show": AppointmentStatus.NO_SHOW,
    "cancel": AppointmentStatus.CANCELLED,
}


# ---------------------------------------------------------------------- access helpers


def require_roles(current_user: User, *roles: UserRole) -> None:
    if current_user.role not in roles:
        raise DomainError("No tenés permisos para esta sección.", status_code=403)


def professional_scope(current_user: User) -> int | None:
    """Professional logins only ever see their own agenda; staff see everyone (None)."""
    if current_user.role != UserRole.PROFESSIONAL:
        return None
    if not current_user.professional_id:
        raise DomainError("Tu usuario no está vinculado a un profesional. Pedíselo a administración.", status_code=403)
    return current_user.professional_id


def ensure_can_manage_professional(current_user: User, professional_id: int) -> None:
    if current_user.role == UserRole.ADMIN:
        return
    if current_user.role == UserRole.PROFESSIONAL and current_user.professional_id == professional_id:
        return
    raise DomainError("No tenés permisos sobre la agenda de ese profesional.", status_code=403)


def ensure_can_touch_appointment(current_user: User, appointment) -> None:
    scope = professional_scope(current_user)
    if scope is not None and appointment.professional_id != scope:
        raise DomainError("Ese turno no es de tu agenda.", status_code=403)


def allowed_actions(current_user: User, appointment) -> list[str]:
    actions = PROFESSIONAL_ACTIONS if current_user.role == UserRole.PROFESSIONAL else STAFF_ACTIONS
    reachable = ALLOWED_TRANSITIONS.get(appointment.status, set())
    return [action for action in ("confirm", "reserve", "complete", "no_show", "cancel") if action in actions and ACTION_TARGETS[action] in reachable]


def _parse_date(value: str | None, default: date) -> date:
    try:
        return date.fromisoformat(value) if value else default
    except ValueError:
        return default


WEEKDAY_SHORT = ("Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom")


def _summarize_availability(rows: list) -> list[dict]:
    """Collapse the day-by-day windows into the handful of schedules they actually repeat.

    Loading two months of recurring availability produces 40+ identical rows; the clinic
    thinks in "lunes a viernes de 9 a 13", so that is what the panel shows.
    """
    by_shift = defaultdict(list)
    for row in rows:
        by_shift[(row.start_time, row.end_time, row.slot_duration_minutes)].append(row)

    summaries = []
    for (start_time, end_time, slot_minutes), shift_rows in by_shift.items():
        shift_rows.sort(key=lambda row: row.availability_date)
        weekdays = sorted({row.availability_date.weekday() for row in shift_rows})
        summaries.append(
            {
                "start_time": start_time,
                "end_time": end_time,
                "slot_minutes": slot_minutes,
                "weekdays": ", ".join(WEEKDAY_SHORT[day] for day in weekdays),
                "first_date": shift_rows[0].availability_date,
                "last_date": shift_rows[-1].availability_date,
                "rows": shift_rows,
            }
        )
    summaries.sort(key=lambda summary: (summary["start_time"], summary["first_date"]))
    return summaries


def _parse_int(value: str | None) -> int | None:
    try:
        return int(value) if value else None
    except ValueError:
        return None


# ---------------------------------------------------------------------- session


@router.get("/app/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": request.query_params.get("error")})


@router.post("/app/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
    auth_service: AuthService = Depends(get_auth_service),
):
    try:
        enforce_login_rate_limit(request, username)
        user = auth_service.authenticate(db, username, password)
        response = RedirectResponse(url="/app", status_code=303)
        auth_service.set_session_cookie(response, auth_service.create_token_for_user(user))
        return response
    except DomainError as exc:
        return redirect_with_message("/app/login", error=exc.detail)


@router.post("/app/logout")
def logout_submit():
    response = RedirectResponse(url="/app/login", status_code=303)
    response.delete_cookie("access_token")
    return response


# ---------------------------------------------------------------------- dashboard


@router.get("/app", response_class=HTMLResponse)
def dashboard(
    request: Request,
    selected_date: str | None = None,
    professional_id: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    professional_service: ProfessionalService = Depends(get_professional_service),
    schedule_service: ScheduleService = Depends(get_schedule_service),
    payment_service: PaymentService = Depends(get_payment_service),
):
    agenda_date = _parse_date(selected_date, clock.today())
    unlinked_professional = current_user.role == UserRole.PROFESSIONAL and not current_user.professional_id
    scope = None if unlinked_professional else professional_scope(current_user)
    selected_professional_id = scope or _parse_int(professional_id)
    appointments = [] if unlinked_professional else schedule_service.get_daily_agenda(
        db, day=agenda_date, professional_id=selected_professional_id
    )
    counts = serialize_status_counts(appointments)

    alerts = []
    if current_user.role in STAFF:
        refunds = payment_service.payments_requiring_refund(db)
        if refunds:
            alerts.append(
                {
                    "text": f"{len(refunds)} seña(s) cobradas de turnos vencidos o cancelados: revisá si corresponde devolverlas.",
                    "href": "/app/payments?filter=refund",
                }
            )
        failed = db.scalar(select(func.count(Notification.id)).where(Notification.status == NotificationStatus.FAILED))
        if failed:
            alerts.append({"text": f"{failed} notificación(es) fallaron después de varios intentos.", "href": "/app/notifications"})
    if unlinked_professional:
        alerts.append({"text": "Tu usuario no está vinculado a un profesional. Pedíselo a administración.", "href": None})

    today = clock.today()
    # The overview looks past today: what is coming in the next seven days, grouped by day.
    upcoming = [] if unlinked_professional else [
        item
        for item in schedule_service.list_appointments(
            db,
            professional_id=selected_professional_id,
            date_from=datetime.combine(today + timedelta(days=1), datetime.min.time()),
            date_to=datetime.combine(today + timedelta(days=7), datetime.max.time()),
        )
        if item.status in UPCOMING_STATUSES
    ]
    upcoming.sort(key=lambda item: item.starts_at)
    upcoming_days = [
        {"label": format_long_date(day).capitalize(), "appointments": list(items)}
        for day, items in groupby(upcoming, key=lambda item: item.starts_at.date())
    ]
    return render_admin(
        request,
        template_name="admin_dashboard.html",
        current_user=current_user,
        page_title="Mi agenda" if scope else "Resumen",
        page_subtitle=f"{format_long_date(today).capitalize()} · hoy y los próximos 7 días",
        active_page="dashboard",
        professionals=[] if scope else active_professionals(db, professional_service),
        appointments=appointments,
        agenda_date=agenda_date.isoformat(),
        agenda_is_today=agenda_date == today,
        agenda_label=format_long_date(agenda_date),
        upcoming_days=upcoming_days,
        selected_professional_id=selected_professional_id,
        is_professional=scope is not None,
        summary={
            "total": len(appointments) - counts["expired"],
            "confirmed": counts["confirmed"],
            "reserved": counts["reserved"],
            "pending_payment": counts["pending_payment"],
            "completed": counts["completed"],
            "no_show": counts["no_show"],
            "attendance_confirmed": sum(1 for item in appointments if item.attendance_confirmed_at),
            "week": len(upcoming),
            "week_confirmed": sum(1 for item in upcoming if item.status == AppointmentStatus.CONFIRMED),
        },
        alerts=alerts,
        actions_for=lambda appointment: allowed_actions(current_user, appointment),
    )


# ---------------------------------------------------------------------- appointments


@router.get("/app/appointments", response_class=HTMLResponse)
def appointments_page(
    request: Request,
    selected_date: str | None = None,
    professional_id: str | None = None,
    status_filter: str | None = None,
    patient_query: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    professional_service: ProfessionalService = Depends(get_professional_service),
    reception_service: ReceptionService = Depends(get_reception_service),
    schedule_service: ScheduleService = Depends(get_schedule_service),
):
    scope = professional_scope(current_user)
    agenda_date = _parse_date(selected_date, clock.today())
    professional_id_value = scope or _parse_int(professional_id)
    normalized_query = (patient_query or "").strip()
    appointments = schedule_service.get_daily_agenda(db, day=agenda_date, professional_id=professional_id_value)
    status_counts = serialize_status_counts(appointments)

    filtered = appointments
    if status_filter:
        filtered = [item for item in filtered if item.status.value == status_filter]
    if normalized_query:
        needle = normalized_query.lower()
        filtered = [
            item
            for item in filtered
            if needle in f"{item.patient.first_name} {item.patient.last_name} {item.patient.dni}".lower()
            or needle in (item.reason or "").lower()
        ]

    filter_params = {"selected_date": agenda_date.isoformat()}
    if professional_id_value and not scope:
        filter_params["professional_id"] = str(professional_id_value)
    if status_filter:
        filter_params["status_filter"] = status_filter
    if normalized_query:
        filter_params["patient_query"] = normalized_query

    professionals = active_professionals(db, professional_service)
    manual_available_dates: dict[str, list[dict]] = {}
    if scope is None:
        for professional in professionals:
            manual_available_dates[str(professional.id)] = [
                {"value": day.isoformat(), "label": format_short_date(day), "slots": count}
                for day, count in schedule_service.list_available_dates(db, professional_id=professional.id, limit=30)
            ]

    return render_admin(
        request,
        template_name="admin_appointments.html",
        current_user=current_user,
        page_title="Turnos",
        page_subtitle=None,
        active_page="appointments",
        professionals=[] if scope else professionals,
        patients=reception_service.list_patients(db) if scope is None else [],
        appointments=filtered,
        agenda_date=agenda_date.isoformat(),
        previous_date=(agenda_date - timedelta(days=1)).isoformat(),
        next_date=(agenda_date + timedelta(days=1)).isoformat(),
        selected_professional_id=professional_id_value,
        selected_status=status_filter,
        patient_query=normalized_query,
        status_options=list(AppointmentStatus),
        stats={
            "total": len(appointments),
            "shown": len(filtered),
            **status_counts,
        },
        filters_querystring=urlencode(filter_params),
        manual_available_dates=manual_available_dates,
        is_professional=scope is not None,
        actions_for=lambda appointment: allowed_actions(current_user, appointment),
    )


@router.post("/app/appointments")
def create_manual_appointment(
    background_tasks: BackgroundTasks,
    patient_id: int = Form(...),
    professional_id: int = Form(...),
    starts_at: str = Form(...),
    duration_minutes: int = Form(30),
    reason: str = Form(""),
    notes: str = Form(""),
    cash_deposit: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    schedule_service: ScheduleService = Depends(get_schedule_service),
    reception_service: ReceptionService = Depends(get_reception_service),
    followup_service: FollowUpService = Depends(get_followup_service),
    payment_service: PaymentService = Depends(get_payment_service),
):
    require_roles(current_user, *STAFF)
    try:
        selected_dt = datetime.fromisoformat(starts_at)
        appointment = schedule_service.create_appointment(
            db,
            AppointmentCreate(
                patient_id=patient_id,
                professional_id=professional_id,
                starts_at=selected_dt,
                duration_minutes=duration_minutes,
                reason=reason or None,
                notes=notes or None,
                created_by=current_user.username,
            ),
            reception_service=reception_service,
            followup_service=followup_service,
            actor=current_user.username,
        )
        deposit = parse_money(cash_deposit)
        if deposit is not None:
            payment_service.register_cash_deposit(db, appointment, deposit, actor=current_user.username)
            db.commit()
    except Exception as exc:
        db.rollback()
        return redirect_with_message("/app/appointments", error=user_facing_message(exc))
    background_tasks.add_task(dispatch_due_notifications, followup_service)
    message = "Turno creado. Le enviamos la confirmación al paciente."
    if deposit is not None:
        message = f"Turno creado con seña de {format_money(deposit)} en efectivo. Le enviamos la confirmación."
    return redirect_with_message(
        f"/app/appointments?selected_date={selected_dt.date().isoformat()}",
        message=message,
    )


@router.post("/app/appointments/series")
def create_appointment_series(
    background_tasks: BackgroundTasks,
    patient_id: int = Form(...),
    professional_id: int = Form(...),
    starts_at: str = Form(...),
    duration_minutes: int = Form(30),
    every_weeks: int = Form(4),
    occurrences: int = Form(6),
    reason: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    schedule_service: ScheduleService = Depends(get_schedule_service),
    reception_service: ReceptionService = Depends(get_reception_service),
    followup_service: FollowUpService = Depends(get_followup_service),
):
    """Carga de una vez los controles de un tratamiento (ortodoncia, seguimientos)."""
    require_roles(current_user, *STAFF)
    try:
        selected_dt = datetime.fromisoformat(starts_at)
        result = schedule_service.create_series(
            db,
            AppointmentSeriesCreate(
                patient_id=patient_id,
                professional_id=professional_id,
                starts_at=selected_dt,
                duration_minutes=duration_minutes,
                every_weeks=every_weeks,
                occurrences=occurrences,
                reason=reason or None,
                notes=notes or None,
                created_by=current_user.username,
            ),
            reception_service=reception_service,
            followup_service=followup_service,
            actor=current_user.username,
        )
    except Exception as exc:
        db.rollback()
        return redirect_with_message("/app/appointments", error=user_facing_message(exc))
    background_tasks.add_task(dispatch_due_notifications, followup_service)
    message = f"Se cargaron {len(result.created)} turnos y le avisamos al paciente."
    if result.skipped:
        fechas = ", ".join(format_short_date(day) for day, _ in result.skipped)
        message += f" No se pudieron cargar {len(result.skipped)}: {fechas}."
    return redirect_with_message(
        f"/app/appointments?selected_date={selected_dt.date().isoformat()}",
        message=message,
    )

@router.post("/app/appointments/{appointment_id}/status")
def update_appointment_status(
    appointment_id: int,
    background_tasks: BackgroundTasks,
    action: str = Form(...),
    return_to: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    schedule_service: ScheduleService = Depends(get_schedule_service),
    followup_service: FollowUpService = Depends(get_followup_service),
):
    # Only redirect back inside the panel.
    target = return_to if return_to.startswith("/app") else "/app/appointments"
    try:
        appointment = schedule_service.get_appointment(db, appointment_id)
        ensure_can_touch_appointment(current_user, appointment)
        if action not in allowed_actions(current_user, appointment):
            raise DomainError("Esa acción no está disponible para este turno.", status_code=409)
        schedule_service.change_status(
            db,
            appointment_id,
            ACTION_TARGETS[action],
            followup_service=followup_service,
            actor=current_user.username,
        )
    except Exception as exc:
        db.rollback()
        return redirect_with_message(target, error=user_facing_message(exc))
    background_tasks.add_task(dispatch_due_notifications, followup_service)
    return redirect_with_message(target, message="Estado del turno actualizado.")


@router.get("/app/appointments/{appointment_id}/edit", response_class=HTMLResponse)
def edit_appointment_page(
    request: Request,
    appointment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    schedule_service: ScheduleService = Depends(get_schedule_service),
):
    require_roles(current_user, *STAFF)
    appointment = schedule_service.get_appointment(db, appointment_id)
    return render_admin(
        request,
        template_name="admin_appointment_edit.html",
        current_user=current_user,
        page_title="Editar turno",
        page_subtitle=None,
        active_page="appointments",
        appointment=appointment,
        status_options=[appointment.status, *sorted(ALLOWED_TRANSITIONS.get(appointment.status, set()), key=lambda s: s.value)],
    )


@router.post("/app/appointments/{appointment_id}/edit")
def edit_appointment_submit(
    appointment_id: int,
    background_tasks: BackgroundTasks,
    starts_at: str = Form(...),
    duration_minutes: int = Form(30),
    status: str = Form(...),
    reason: str = Form(""),
    notes: str = Form(""),
    charged_amount: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    schedule_service: ScheduleService = Depends(get_schedule_service),
    followup_service: FollowUpService = Depends(get_followup_service),
):
    require_roles(current_user, *STAFF)
    try:
        appointment = schedule_service.update_appointment(
            db,
            appointment_id,
            AppointmentUpdate(
                starts_at=datetime.fromisoformat(starts_at),
                duration_minutes=duration_minutes,
                status=AppointmentStatus(status),
                reason=reason or None,
                notes=notes or None,
                charged_amount=parse_money(charged_amount),
            ),
            followup_service=followup_service,
            actor=current_user.username,
        )
    except Exception as exc:
        db.rollback()
        return redirect_with_message(f"/app/appointments/{appointment_id}/edit", error=user_facing_message(exc))
    background_tasks.add_task(dispatch_due_notifications, followup_service)
    return redirect_with_message(
        f"/app/appointments?selected_date={appointment.starts_at.date().isoformat()}",
        message="Turno actualizado.",
    )


# ---------------------------------------------------------------------- waitlist


@router.get("/app/waitlist", response_class=HTMLResponse)
def waitlist_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    professional_service: ProfessionalService = Depends(get_professional_service),
):
    require_roles(current_user, *STAFF)
    entries = WaitlistService().list_entries(db)
    return render_admin(
        request,
        template_name="admin_waitlist.html",
        current_user=current_user,
        page_title="Lista de espera",
        page_subtitle="Cuando se libera un horario, se les avisa por email a los primeros que les sirva.",
        active_page="waitlist",
        entries=entries,
        professionals=active_professionals(db, professional_service),
        period_labels=WAITLIST_PERIOD_LABELS,
        status_labels=WAITLIST_STATUS_LABELS,
    )


@router.post("/app/waitlist/{entry_id}/status")
def waitlist_set_status(
    entry_id: int,
    status: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_roles(current_user, *STAFF)
    try:
        WaitlistService().set_status(db, entry_id, WaitlistStatus(status), actor=current_user.username)
    except Exception as exc:
        db.rollback()
        return redirect_with_message("/app/waitlist", error=user_facing_message(exc))
    return redirect_with_message("/app/waitlist", message="Lista de espera actualizada.")


# ---------------------------------------------------------------------- patients


@router.get("/app/patients", response_class=HTMLResponse)
def patients_page(
    request: Request,
    query: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    reception_service: ReceptionService = Depends(get_reception_service),
):
    require_roles(current_user, *STAFF)
    patients = filter_patients_collection(reception_service.list_patients(db), query)
    return render_admin(
        request,
        template_name="admin_patients.html",
        current_user=current_user,
        page_title="Pacientes",
        page_subtitle=None,
        active_page="patients",
        patients=patients,
        query=query or "",
    )


@router.post("/app/patients")
def create_patient_from_admin(
    dni: str = Form(...),
    first_name: str = Form(...),
    last_name: str = Form(...),
    email: str = Form(""),
    phone: str = Form(""),
    observations: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    reception_service: ReceptionService = Depends(get_reception_service),
):
    require_roles(current_user, *STAFF)
    try:
        reception_service.create_patient(
            db,
            PatientCreate(
                dni=dni,
                first_name=first_name,
                last_name=last_name,
                email=email or None,
                phone=phone or None,
                observations=observations or None,
            ),
            actor=current_user.username,
        )
    except Exception as exc:
        db.rollback()
        return redirect_with_message("/app/patients", error=user_facing_message(exc))
    return redirect_with_message("/app/patients", message="Paciente creado.")


@router.post("/app/patients/{patient_id}/delete")
def delete_patient_from_admin(
    patient_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    reception_service: ReceptionService = Depends(get_reception_service),
):
    require_roles(current_user, *STAFF)
    try:
        reception_service.delete_patient(db, patient_id, actor=current_user.username)
    except Exception as exc:
        db.rollback()
        return redirect_with_message("/app/patients", error=user_facing_message(exc))
    return redirect_with_message("/app/patients", message="Paciente eliminado.")


@router.get("/app/patients/{patient_id}/edit", response_class=HTMLResponse)
def edit_patient_page(
    request: Request,
    patient_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    reception_service: ReceptionService = Depends(get_reception_service),
):
    require_roles(current_user, *STAFF)
    patient = reception_service.get_patient(db, patient_id)
    history = sorted(patient.appointments, key=lambda item: item.starts_at, reverse=True)[:20]
    return render_admin(
        request,
        template_name="admin_patient_edit.html",
        current_user=current_user,
        page_title=f"{patient.first_name} {patient.last_name}",
        page_subtitle=f"DNI {patient.dni}",
        active_page="patients",
        patient=patient,
        history=history,
    )


@router.post("/app/patients/{patient_id}/edit")
def edit_patient_submit(
    patient_id: int,
    dni: str = Form(...),
    first_name: str = Form(...),
    last_name: str = Form(...),
    email: str = Form(""),
    phone: str = Form(""),
    observations: str = Form(""),
    is_active: bool = Form(False),
    birth_date: str = Form(""),
    address: str = Form(""),
    city: str = Form(""),
    health_insurance: str = Form(""),
    health_insurance_number: str = Form(""),
    emergency_contact: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    reception_service: ReceptionService = Depends(get_reception_service),
):
    require_roles(current_user, *STAFF)
    try:
        reception_service.update_patient(
            db,
            patient_id,
            PatientUpdate(
                dni=dni,
                first_name=first_name,
                last_name=last_name,
                email=email or None,
                phone=phone or None,
                observations=observations or None,
                is_active=is_active,
                birth_date=date.fromisoformat(birth_date) if birth_date else None,
                address=address or None,
                city=city or None,
                health_insurance=health_insurance or None,
                health_insurance_number=health_insurance_number or None,
                emergency_contact=emergency_contact or None,
            ),
            actor=current_user.username,
        )
    except Exception as exc:
        db.rollback()
        return redirect_with_message(f"/app/patients/{patient_id}/edit", error=user_facing_message(exc))
    return redirect_with_message("/app/patients", message="Paciente actualizado.")


# ---------------------------------------------------------------------- professionals


@router.get("/app/professionals", response_class=HTMLResponse)
def professionals_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    professional_service: ProfessionalService = Depends(get_professional_service),
    schedule_service: ScheduleService = Depends(get_schedule_service),
    auth_service: AuthService = Depends(get_auth_service),
):
    require_roles(current_user, *ADMIN_ONLY)
    windows_count = defaultdict(int)
    for row in schedule_service.list_availability_windows(db, date_from=clock.today()):
        windows_count[row.professional_id] += 1
    logins = {user.professional_id: user for user in auth_service.list_users(db) if user.professional_id}
    return render_admin(
        request,
        template_name="admin_professionals.html",
        current_user=current_user,
        page_title="Profesionales",
        page_subtitle=None,
        active_page="professionals",
        professionals=professional_service.list_professionals(db),
        windows_count=windows_count,
        logins=logins,
    )


@router.post("/app/professionals")
def create_professional_from_admin(
    first_name: str = Form(...),
    last_name: str = Form(...),
    specialty: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    default_appointment_duration: int = Form(30),
    deposit_amount: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    professional_service: ProfessionalService = Depends(get_professional_service),
):
    require_roles(current_user, *ADMIN_ONLY)
    try:
        professional_service.create_professional(
            db,
            ProfessionalCreate(
                first_name=first_name,
                last_name=last_name,
                specialty=specialty or None,
                email=email or None,
                phone=phone or None,
                default_appointment_duration=default_appointment_duration,
                deposit_amount=parse_money(deposit_amount),
            ),
            actor=current_user.username,
        )
    except Exception as exc:
        db.rollback()
        return redirect_with_message("/app/professionals", error=user_facing_message(exc))
    return redirect_with_message("/app/professionals", message="Profesional creado.")


@router.get("/app/professionals/{professional_id}/edit", response_class=HTMLResponse)
def edit_professional_page(
    request: Request,
    professional_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    professional_service: ProfessionalService = Depends(get_professional_service),
):
    require_roles(current_user, *ADMIN_ONLY)
    return render_admin(
        request,
        template_name="admin_professional_edit.html",
        current_user=current_user,
        page_title="Editar profesional",
        page_subtitle=None,
        active_page="professionals",
        professional=professional_service.get_professional(db, professional_id),
    )


@router.post("/app/professionals/{professional_id}/edit")
def edit_professional_submit(
    professional_id: int,
    first_name: str = Form(...),
    last_name: str = Form(...),
    specialty: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    default_appointment_duration: int = Form(30),
    deposit_amount: str = Form(""),
    is_active: bool = Form(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    professional_service: ProfessionalService = Depends(get_professional_service),
):
    require_roles(current_user, *ADMIN_ONLY)
    try:
        professional_service.update_professional(
            db,
            professional_id,
            ProfessionalUpdate(
                first_name=first_name,
                last_name=last_name,
                specialty=specialty or None,
                email=email or None,
                phone=phone or None,
                default_appointment_duration=default_appointment_duration,
                deposit_amount=parse_money(deposit_amount),
                is_active=is_active,
            ),
            actor=current_user.username,
        )
    except Exception as exc:
        db.rollback()
        return redirect_with_message(f"/app/professionals/{professional_id}/edit", error=user_facing_message(exc))
    return redirect_with_message("/app/professionals", message="Profesional actualizado.")


@router.post("/app/professionals/{professional_id}/delete")
def delete_professional_from_admin(
    professional_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    professional_service: ProfessionalService = Depends(get_professional_service),
):
    require_roles(current_user, *ADMIN_ONLY)
    try:
        professional_service.delete_professional(db, professional_id, actor=current_user.username)
    except Exception as exc:
        db.rollback()
        return redirect_with_message("/app/professionals", error=user_facing_message(exc))
    return redirect_with_message("/app/professionals", message="Profesional eliminado.")


# ---------------------------------------------------------------------- availability


@router.get("/app/settings")
def legacy_settings_redirect():
    return RedirectResponse("/app/availability", status_code=301)


@router.get("/app/availability", response_class=HTMLResponse)
def availability_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    professional_service: ProfessionalService = Depends(get_professional_service),
    schedule_service: ScheduleService = Depends(get_schedule_service),
):
    require_roles(current_user, UserRole.ADMIN, UserRole.PROFESSIONAL)
    scope = professional_scope(current_user)
    professionals = [item for item in active_professionals(db, professional_service) if scope is None or item.id == scope]
    grouped_windows = defaultdict(list)
    for row in schedule_service.list_availability_windows(db, professional_id=scope, date_from=clock.today()):
        grouped_windows[row.professional_id].append(row)
    schedules = {pid: _summarize_availability(rows) for pid, rows in grouped_windows.items()}
    return render_admin(
        request,
        template_name="admin_availability.html",
        current_user=current_user,
        page_title="Mi disponibilidad" if scope else "Disponibilidad",
        page_subtitle="Los días y horarios que se ofrecen para reservar online.",
        active_page="availability",
        professionals=professionals,
        grouped_windows=grouped_windows,
        schedules=schedules,
        today=clock.today().isoformat(),
        default_until=(clock.today() + timedelta(days=28)).isoformat(),
    )


@router.post("/app/availability/windows")
def create_availability_window_from_admin(
    professional_id: int = Form(...),
    availability_date: str = Form(...),
    start_time: str = Form(...),
    end_time: str = Form(...),
    slot_duration_minutes: int = Form(30),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    schedule_service: ScheduleService = Depends(get_schedule_service),
):
    try:
        ensure_can_manage_professional(current_user, professional_id)
        schedule_service.create_availability_window(
            db,
            AvailabilityWindowCreate(
                professional_id=professional_id,
                availability_date=date.fromisoformat(availability_date),
                start_time=datetime.strptime(start_time, "%H:%M").time(),
                end_time=datetime.strptime(end_time, "%H:%M").time(),
                slot_duration_minutes=slot_duration_minutes,
                notes=notes or None,
            ),
            actor=current_user.username,
        )
    except Exception as exc:
        db.rollback()
        return redirect_with_message("/app/availability", error=user_facing_message(exc))
    return redirect_with_message("/app/availability", message="Disponibilidad guardada.")


@router.post("/app/availability/recurring")
def create_recurring_availability_from_admin(
    professional_id: int = Form(...),
    date_from: str = Form(...),
    date_to: str = Form(...),
    weekdays: list[int] = Form(default=[]),
    start_time: str = Form(...),
    end_time: str = Form(...),
    slot_duration_minutes: int = Form(30),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    schedule_service: ScheduleService = Depends(get_schedule_service),
):
    try:
        ensure_can_manage_professional(current_user, professional_id)
        result = schedule_service.create_recurring_windows(
            db,
            RecurringAvailabilityCreate(
                professional_id=professional_id,
                date_from=date.fromisoformat(date_from),
                date_to=date.fromisoformat(date_to),
                weekdays=weekdays,
                start_time=datetime.strptime(start_time, "%H:%M").time(),
                end_time=datetime.strptime(end_time, "%H:%M").time(),
                slot_duration_minutes=slot_duration_minutes,
                notes=notes or None,
            ),
            actor=current_user.username,
        )
    except Exception as exc:
        db.rollback()
        return redirect_with_message("/app/availability", error=user_facing_message(exc))
    message = f"Se cargaron {result.created} día(s)."
    if result.skipped_dates:
        message += f" Se salteó {len(result.skipped_dates)} día(s) que ya tenían horarios superpuestos o ya pasaron."
    return redirect_with_message("/app/availability", message=message)


@router.post("/app/availability/clear")
def clear_availability_from_admin(
    professional_id: int = Form(...),
    date_from: str = Form(...),
    date_to: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    schedule_service: ScheduleService = Depends(get_schedule_service),
):
    try:
        ensure_can_manage_professional(current_user, professional_id)
        result = schedule_service.clear_windows(
            db,
            professional_id=professional_id,
            date_from=date.fromisoformat(date_from),
            date_to=date.fromisoformat(date_to),
            actor=current_user.username,
        )
    except Exception as exc:
        db.rollback()
        return redirect_with_message("/app/availability", error=user_facing_message(exc))
    message = f"Se liberaron {result.removed} bloque(s) de disponibilidad."
    if result.skipped_dates:
        kept = ", ".join(format_short_date(day) for day in result.skipped_dates[:5])
        message += f" Quedaron {len(result.skipped_dates)} día(s) con turnos activos ({kept}): cancelalos o reprogramalos primero."
    return redirect_with_message("/app/availability", message=message)


@router.post("/app/availability/windows/{availability_window_id}/delete")
def delete_availability_window_from_admin(
    availability_window_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    schedule_service: ScheduleService = Depends(get_schedule_service),
):
    try:
        window = schedule_service.get_availability_window(db, availability_window_id)
        ensure_can_manage_professional(current_user, window.professional_id)
        schedule_service.delete_availability_window(db, availability_window_id, actor=current_user.username)
    except Exception as exc:
        db.rollback()
        return redirect_with_message("/app/availability", error=user_facing_message(exc))
    return redirect_with_message("/app/availability", message="Disponibilidad eliminada.")


# ---------------------------------------------------------------------- notifications


@router.get("/app/notifications", response_class=HTMLResponse)
def notifications_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    followup_service: FollowUpService = Depends(get_followup_service),
):
    require_roles(current_user, *ADMIN_ONLY)
    counts = dict(
        db.execute(select(Notification.status, func.count(Notification.id)).group_by(Notification.status)).all()
    )
    channel_counts = dict(
        db.execute(
            select(Notification.channel, func.count(Notification.id))
            .where(Notification.status == NotificationStatus.SENT)
            .group_by(Notification.channel)
        ).all()
    )
    return render_admin(
        request,
        template_name="admin_notifications.html",
        current_user=current_user,
        page_title="Notificaciones",
        page_subtitle="Emails y WhatsApp a pacientes y avisos a los profesionales. Los que fallan se reintentan solos.",
        type_labels=NOTIFICATION_TYPE_LABELS,
        active_page="notifications",
        counts={status.value: counts.get(status, 0) for status in NotificationStatus},
        sent_by_channel={channel.value: channel_counts.get(channel, 0) for channel in NotificationChannel},
        notifications=followup_service.list_notifications(db, limit=100),
        smtp_configured=followup_service.email_client.is_configured(),
        whatsapp_configured=followup_service.whatsapp_client.is_configured(),
        smtp_sender=followup_service.settings.email_from,
        reminder_hours_ahead=followup_service.settings.reminder_hours_ahead,
    )


@router.post("/app/notifications/prepare")
def prepare_reminders_from_admin(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    followup_service: FollowUpService = Depends(get_followup_service),
):
    require_roles(current_user, *ADMIN_ONLY)
    prepared = followup_service.prepare_upcoming_reminders(db, actor=current_user.username)
    return redirect_with_message("/app/notifications", message=f"Recordatorios preparados: {prepared}.")


@router.post("/app/notifications/send")
def send_notifications_from_admin(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    followup_service: FollowUpService = Depends(get_followup_service),
):
    require_roles(current_user, *ADMIN_ONLY)
    result = followup_service.send_pending_notifications(db, limit=200, actor=current_user.username)
    return redirect_with_message(
        "/app/notifications",
        message=(
            f"Enviadas: {result['sent']} · reintentando: {result['retrying']} · "
            f"fallidas: {result['failed']} · omitidas: {result['skipped']}."
        ),
    )


# ---------------------------------------------------------------------- payments & metrics


@router.get("/app/payments", response_class=HTMLResponse)
def payments_page(
    request: Request,
    filter: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    payment_service: PaymentService = Depends(get_payment_service),
):
    require_roles(current_user, *ADMIN_ONLY)
    refunds = payment_service.payments_requiring_refund(db)
    payments = refunds if filter == "refund" else payment_service.list_payments(db, limit=200)
    return render_admin(
        request,
        template_name="admin_payments.html",
        current_user=current_user,
        page_title="Pagos",
        page_subtitle=None,
        active_page="payments",
        payments=payments,
        refund_ids={payment.id for payment in refunds},
        refund_count=len(refunds),
        filter=filter,
        gateway_name=payment_service.gateway.name if payment_service.gateway else None,
    )


@router.post("/app/payments/{payment_id}/refund")
def mark_payment_refunded(
    payment_id: int,
    return_to: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    payment_service: PaymentService = Depends(get_payment_service),
):
    """Leaves a refund made by hand on record; Mercado Pago's own refunds arrive by webhook."""
    require_roles(current_user, *ADMIN_ONLY)
    target = return_to if return_to.startswith("/app") else "/app/payments?filter=refund"
    try:
        payment_service.mark_refunded(db, payment_id, actor=current_user.username)
    except Exception as exc:
        db.rollback()
        return redirect_with_message(target, error=user_facing_message(exc))
    return redirect_with_message(target, message="Seña marcada como devuelta.")


def _metrics_period(date_from: str | None, date_to: str | None) -> tuple[date, date]:
    """Defaults to the current month, so upcoming bookings count toward occupancy too."""
    today = clock.today()
    month_start = today.replace(day=1)
    month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    start = _parse_date(date_from, month_start)
    end = _parse_date(date_to, month_end)
    if start > end:
        start, end = end, start
    return start, min(end, start + timedelta(days=366))


@router.get("/app/metrics", response_class=HTMLResponse)
def metrics_page(
    request: Request,
    date_from: str | None = None,
    date_to: str | None = None,
    professional_id: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    professional_service: ProfessionalService = Depends(get_professional_service),
):
    require_roles(current_user, *ADMIN_ONLY)
    start, end = _metrics_period(date_from, date_to)
    selected_professional_id = _parse_int(professional_id)
    stats = AnalyticsService().clinic_stats(db, date_from=start, date_to=end, professional_id=selected_professional_id)
    export_params = {"date_from": start.isoformat(), "date_to": end.isoformat()}
    if selected_professional_id:
        export_params["professional_id"] = str(selected_professional_id)
    return render_admin(
        request,
        template_name="admin_metrics.html",
        current_user=current_user,
        page_title="Métricas",
        page_subtitle=None,
        active_page="metrics",
        stats=stats,
        date_from=start.isoformat(),
        date_to=end.isoformat(),
        professionals=professional_service.list_professionals(db),
        selected_professional_id=selected_professional_id,
        export_query=urlencode(export_params),
    )


@router.get("/app/metrics/export.csv")
def metrics_export(
    date_from: str | None = None,
    date_to: str | None = None,
    professional_id: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_roles(current_user, *ADMIN_ONLY)
    start, end = _metrics_period(date_from, date_to)
    content = AnalyticsService().export_appointments_csv(
        db, date_from=start, date_to=end, professional_id=_parse_int(professional_id)
    )
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="turnos_{start:%Y%m%d}_{end:%Y%m%d}.csv"'},
    )


# ---------------------------------------------------------------------- users


@router.get("/app/users", response_class=HTMLResponse)
def users_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
    professional_service: ProfessionalService = Depends(get_professional_service),
):
    require_roles(current_user, *ADMIN_ONLY)
    users = auth_service.list_users(db)
    linked = {user.professional_id for user in users if user.professional_id}
    professionals = professional_service.list_professionals(db)
    return render_admin(
        request,
        template_name="admin_users.html",
        current_user=current_user,
        page_title="Usuarios",
        page_subtitle=None,
        active_page="users",
        users=users,
        professionals=professionals,
        professionals_by_id={item.id: item for item in professionals},
        unlinked_professionals=[item for item in professionals if item.id not in linked],
        role_labels=ROLE_LABELS,
        roles=list(UserRole),
    )


@router.post("/app/users")
def create_user_from_admin(
    username: str = Form(...),
    full_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
    professional_id: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
):
    require_roles(current_user, *ADMIN_ONLY)
    try:
        auth_service.create_user(
            db,
            UserCreate(
                username=username.strip(),
                full_name=full_name.strip(),
                email=email.strip(),
                password=password,
                role=UserRole(role),
                professional_id=_parse_int(professional_id),
            ),
            actor=current_user.username,
        )
    except Exception as exc:
        db.rollback()
        return redirect_with_message("/app/users", error=user_facing_message(exc))
    return redirect_with_message("/app/users", message="Usuario creado. Compartile la contraseña por un canal seguro.")


@router.post("/app/users/{user_id}")
def update_user_from_admin(
    user_id: int,
    role: str = Form(...),
    professional_id: str = Form(""),
    is_active: bool = Form(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
):
    require_roles(current_user, *ADMIN_ONLY)
    try:
        auth_service.update_user(
            db,
            user_id,
            UserUpdate(role=UserRole(role), professional_id=_parse_int(professional_id), is_active=is_active),
            actor=current_user,
        )
    except Exception as exc:
        db.rollback()
        return redirect_with_message("/app/users", error=user_facing_message(exc))
    return redirect_with_message("/app/users", message="Usuario actualizado.")


@router.post("/app/users/{user_id}/password")
def reset_user_password_from_admin(
    user_id: int,
    password: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
):
    require_roles(current_user, *ADMIN_ONLY)
    try:
        user = auth_service.set_password(db, user_id, password, actor=current_user)
    except Exception as exc:
        db.rollback()
        return redirect_with_message("/app/users", error=user_facing_message(exc))
    response = redirect_with_message("/app/users", message="Contraseña actualizada.")
    # The change closes every session of that user. When it is their own, the browser that made the
    # change gets a fresh session instead of being logged out.
    if user.id == current_user.id:
        auth_service.set_session_cookie(response, auth_service.create_token_for_user(user))
    return response
