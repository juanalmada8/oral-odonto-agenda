from collections import defaultdict
from datetime import date, datetime
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.api.deps import (
    get_auth_service,
    get_current_user,
    get_followup_agent,
    get_professional_service,
    get_reception_agent,
    get_schedule_agent,
)
from app.core.enums import AppointmentStatus, NotificationStatus, UserRole
from app.core.exceptions import DomainError
from app.db.session import get_db
from app.models.user import User
from app.schemas.appointment import AppointmentCreate, AppointmentUpdate
from app.schemas.availability import AvailabilityWindowCreate
from app.schemas.patient import PatientCreate, PatientUpdate, PatientUpsert
from app.schemas.professional import ProfessionalCreate, ProfessionalUpdate
from app.services.auth_service import AuthService
from app.services.followup_agent import FollowUpAgent
from app.services.professional_service import ProfessionalService
from app.services.reception_agent import ReceptionAgent
from app.services.schedule_agent import ScheduleAgent


templates = Jinja2Templates(directory="app/templates")
router = APIRouter(include_in_schema=False)

DAY_LABELS = {
    0: "Lunes",
    1: "Martes",
    2: "Miercoles",
    3: "Jueves",
    4: "Viernes",
    5: "Sabado",
    6: "Domingo",
}


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


@router.get("/reservar", response_class=HTMLResponse)
def public_booking_page(
    request: Request,
    selected_date: date | None = None,
    professional_id: str | None = None,
    booking_id: int | None = None,
    db: Session = Depends(get_db),
    professional_service: ProfessionalService = Depends(get_professional_service),
    schedule_agent: ScheduleAgent = Depends(get_schedule_agent),
):
    professionals = active_professionals(db, professional_service)
    agenda_date = selected_date or date.today()
    selected_professional = None
    available_slots = []
    available_dates: list[dict[str, str | int]] = []
    booking_summary: dict[str, str] | None = None

    professional_id_value = int(professional_id) if professional_id else None

    if professionals:
        selected_professional = professionals[0] if professional_id_value is None else next(
            (professional for professional in professionals if professional.id == professional_id_value),
            None,
        )
        if selected_professional:
            available_dates_raw = schedule_agent.list_available_dates(
                db,
                professional_id=selected_professional.id,
                date_from=date.today(),
            )
            available_dates = [
                {
                    "value": available_day.isoformat(),
                    "label": available_day.strftime("%d/%m/%Y"),
                    "slots": slot_count,
                }
                for available_day, slot_count in available_dates_raw
            ]
            available_date_values = {item["value"] for item in available_dates}
            if available_dates and agenda_date.isoformat() not in available_date_values:
                agenda_date = date.fromisoformat(available_dates[0]["value"])
            available_slots = schedule_agent.get_daily_availability(
                db,
                professional_id=selected_professional.id,
                day=agenda_date,
            )

    if booking_id:
        try:
            booked = schedule_agent.get_appointment(db, booking_id)
            if selected_professional and booked.professional_id == selected_professional.id:
                booking_summary = {
                    "professional": f"{booked.professional.first_name} {booked.professional.last_name}",
                    "date": booked.starts_at.strftime("%d/%m/%Y"),
                    "time": booked.starts_at.strftime("%H:%M"),
                    "status": booked.status.value,
                }
        except DomainError:
            booking_summary = None

    return templates.TemplateResponse(
        request,
        "public_booking.html",
        {
            "professionals": professionals,
            "selected_professional": selected_professional,
            "selected_date": agenda_date.isoformat(),
            "selected_date_label": agenda_date.strftime("%d/%m/%Y"),
            "available_dates": available_dates,
            "available_slots": available_slots,
            "booking_summary": booking_summary,
            "message": request.query_params.get("message"),
            "error": request.query_params.get("error"),
        },
    )


@router.post("/reservar")
def create_public_booking(
    professional_id: int = Form(...),
    starts_at: str = Form(...),
    dni: str = Form(...),
    first_name: str = Form(...),
    last_name: str = Form(...),
    email: str = Form(""),
    phone: str = Form(""),
    observations: str = Form(""),
    reason: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    schedule_agent: ScheduleAgent = Depends(get_schedule_agent),
    reception_agent: ReceptionAgent = Depends(get_reception_agent),
    followup_agent: FollowUpAgent = Depends(get_followup_agent),
):
    selected_dt = datetime.fromisoformat(starts_at)
    redirect_base = f"/reservar?professional_id={professional_id}&selected_date={selected_dt.date().isoformat()}"

    try:
        appointment = schedule_agent.create_appointment(
            db,
            AppointmentCreate(
                professional_id=professional_id,
                patient=PatientUpsert(
                    dni=dni,
                    first_name=first_name,
                    last_name=last_name,
                    email=email or None,
                    phone=phone or None,
                    observations=observations or None,
                ),
                starts_at=selected_dt,
                reason=reason or "Reserva online",
                notes=notes or "Generado desde reserva publica",
                created_by="public_booking",
            ),
            reception_agent=reception_agent,
            followup_agent=followup_agent,
            actor="public_booking",
        )
        success_path = (
            f"/reservar?professional_id={professional_id}"
            f"&selected_date={selected_dt.date().isoformat()}"
            f"&booking_id={appointment.id}"
        )
        return redirect_with_message(
            success_path,
            message="Tu turno fue reservado. Si cargaste email, te vamos a enviar la confirmacion.",
            fragment="booking-flow",
        )
    except Exception as exc:
        return redirect_with_message(redirect_base, error=str(exc), fragment="booking-flow")


@router.get("/app/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "error": request.query_params.get("error"),
        },
    )


@router.post("/app/login")
def login_submit(
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
    auth_service: AuthService = Depends(get_auth_service),
):
    try:
        user = auth_service.authenticate(db, username, password)
        token = auth_service.create_token_for_user(user)
        response = RedirectResponse(url="/app", status_code=303)
        response.set_cookie(
            key="access_token",
            value=f"Bearer {token}",
            httponly=True,
            samesite="lax",
            max_age=auth_service.settings.access_token_expire_minutes * 60,
        )
        return response
    except DomainError as exc:
        return redirect_with_message("/app/login", error=exc.detail)


@router.post("/app/logout")
def logout_submit():
    response = RedirectResponse(url="/app/login", status_code=303)
    response.delete_cookie("access_token")
    return response


@router.get("/app", response_class=HTMLResponse)
def dashboard(
    request: Request,
    selected_date: date | None = None,
    professional_id: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    professional_service: ProfessionalService = Depends(get_professional_service),
    schedule_agent: ScheduleAgent = Depends(get_schedule_agent),
    followup_agent: FollowUpAgent = Depends(get_followup_agent),
):
    agenda_date = selected_date or date.today()
    professional_id_value = int(professional_id) if professional_id else None
    professionals = active_professionals(db, professional_service)
    appointments = schedule_agent.get_daily_agenda(db, day=agenda_date, professional_id=professional_id_value)
    counts = serialize_status_counts(appointments)
    notifications = followup_agent.list_notifications(db)
    pending_notifications = [item for item in notifications if item.status == NotificationStatus.PENDING]
    summary = {
        "total": len(appointments),
        "reserved": counts[AppointmentStatus.RESERVED.value],
        "confirmed": counts[AppointmentStatus.CONFIRMED.value],
        "completed": counts[AppointmentStatus.COMPLETED.value],
        "cancelled": counts[AppointmentStatus.CANCELLED.value],
        "pending_notifications": len(pending_notifications),
    }
    return render_admin(
        request,
        template_name="admin_dashboard.html",
        current_user=current_user,
        page_title="Dashboard operativo",
        page_subtitle="La agenda del dia es el centro de la operacion. El resto acompaña.",
        active_page="dashboard",
        professionals=professionals,
        appointments=appointments,
        agenda_date=agenda_date.isoformat(),
        selected_professional_id=professional_id_value,
        summary=summary,
        next_actions=[
            {"label": "Gestionar turnos", "href": "/app/appointments", "meta": "Cambios manuales, filtros y estados"},
            {"label": "Gestionar pacientes", "href": "/app/patients", "meta": "Edición puntual y control por DNI"},
            *(
                [{"label": "Configurar agenda", "href": "/app/settings", "meta": "Disponibilidad puntual y recordatorios"}]
                if current_user.role == UserRole.ADMIN
                else []
            ),
        ],
        pending_notifications=pending_notifications[:5],
    )


@router.get("/app/appointments", response_class=HTMLResponse)
def appointments_page(
    request: Request,
    selected_date: date | None = None,
    professional_id: str | None = None,
    status_filter: str | None = None,
    patient_query: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    professional_service: ProfessionalService = Depends(get_professional_service),
    reception_agent: ReceptionAgent = Depends(get_reception_agent),
    schedule_agent: ScheduleAgent = Depends(get_schedule_agent),
):
    agenda_date = selected_date or date.today()
    professional_id_value = int(professional_id) if professional_id else None
    normalized_patient_query = (patient_query or "").strip()
    professionals = active_professionals(db, professional_service)
    patients = reception_agent.list_patients(db)
    appointments = schedule_agent.get_daily_agenda(db, day=agenda_date, professional_id=professional_id_value)
    status_counts = serialize_status_counts(appointments)
    filtered_appointments = appointments

    if status_filter:
        filtered_appointments = [
            appointment for appointment in filtered_appointments if appointment.status.value == status_filter
        ]
    if normalized_patient_query:
        query = normalized_patient_query.lower()
        filtered_appointments = [
            appointment
            for appointment in filtered_appointments
            if query in appointment.patient.first_name.lower()
            or query in appointment.patient.last_name.lower()
            or query in appointment.patient.dni.lower()
            or query in appointment.professional.first_name.lower()
            or query in appointment.professional.last_name.lower()
            or query in (appointment.reason or "").lower()
        ]

    filter_params = {"selected_date": agenda_date.isoformat()}
    if professional_id_value:
        filter_params["professional_id"] = str(professional_id_value)
    if status_filter:
        filter_params["status_filter"] = status_filter
    if normalized_patient_query:
        filter_params["patient_query"] = normalized_patient_query
    filters_querystring = urlencode(filter_params)

    return render_admin(
        request,
        template_name="admin_appointments.html",
        current_user=current_user,
        page_title="Turnos",
        page_subtitle="Gestion manual ordenada de la agenda y sus estados.",
        active_page="appointments",
        professionals=professionals,
        patients=patients,
        appointments=filtered_appointments,
        agenda_date=agenda_date.isoformat(),
        selected_professional_id=professional_id_value,
        selected_status=status_filter,
        patient_query=normalized_patient_query,
        status_options=[status.value for status in AppointmentStatus],
        stats={
            "total": len(appointments),
            "reserved": status_counts[AppointmentStatus.RESERVED.value],
            "confirmed": status_counts[AppointmentStatus.CONFIRMED.value],
            "completed": status_counts[AppointmentStatus.COMPLETED.value],
            "cancelled": status_counts[AppointmentStatus.CANCELLED.value],
            "shown": len(filtered_appointments),
        },
        filters_querystring=filters_querystring,
    )


@router.post("/app/appointments")
def create_manual_appointment(
    patient_id: int = Form(...),
    professional_id: int = Form(...),
    starts_at: str = Form(...),
    duration_minutes: int = Form(30),
    reason: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    schedule_agent: ScheduleAgent = Depends(get_schedule_agent),
    reception_agent: ReceptionAgent = Depends(get_reception_agent),
    followup_agent: FollowUpAgent = Depends(get_followup_agent),
):
    selected_dt = datetime.fromisoformat(starts_at)
    try:
        schedule_agent.create_appointment(
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
            reception_agent=reception_agent,
            followup_agent=followup_agent,
            actor=current_user.username,
        )
        return redirect_with_message(
            f"/app/appointments?selected_date={selected_dt.date().isoformat()}",
            message="Turno manual creado",
        )
    except Exception as exc:
        return redirect_with_message("/app/appointments", error=str(exc))


@router.post("/app/appointments/{appointment_id}/status")
def update_appointment_status(
    appointment_id: int,
    action: str = Form(...),
    selected_date: str = Form(""),
    professional_id: str = Form(""),
    status_filter: str = Form(""),
    patient_query: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    schedule_agent: ScheduleAgent = Depends(get_schedule_agent),
):
    redirect_params = {"selected_date": selected_date or date.today().isoformat()}
    if professional_id:
        redirect_params["professional_id"] = professional_id
    if status_filter:
        redirect_params["status_filter"] = status_filter
    if patient_query:
        redirect_params["patient_query"] = patient_query

    try:
        if action == "confirm":
            appointment = schedule_agent.confirm_appointment(db, appointment_id, actor=current_user.username)
        elif action == "complete":
            appointment = schedule_agent.complete_appointment(db, appointment_id, actor=current_user.username)
        elif action == "cancel":
            appointment = schedule_agent.cancel_appointment(db, appointment_id, actor=current_user.username)
        else:
            raise DomainError("Unsupported appointment action", status_code=400)
        redirect_params["selected_date"] = selected_date or appointment.starts_at.date().isoformat()
        if professional_id:
            redirect_params["professional_id"] = professional_id
        if status_filter:
            redirect_params["status_filter"] = status_filter
        if patient_query:
            redirect_params["patient_query"] = patient_query

        return redirect_with_message(
            f"/app/appointments?{urlencode(redirect_params)}",
            message="Estado de turno actualizado",
        )
    except Exception as exc:
        return redirect_with_message(f"/app/appointments?{urlencode(redirect_params)}", error=str(exc))


@router.get("/app/appointments/{appointment_id}/edit", response_class=HTMLResponse)
def edit_appointment_page(
    request: Request,
    appointment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    schedule_agent: ScheduleAgent = Depends(get_schedule_agent),
):
    appointment = schedule_agent.get_appointment(db, appointment_id)
    return render_admin(
        request,
        template_name="admin_appointment_edit.html",
        current_user=current_user,
        page_title="Editar turno",
        page_subtitle="Reprogramacion y ajuste manual desde una vista secundaria.",
        active_page="appointments",
        appointment=appointment,
        status_options=[status.value for status in AppointmentStatus],
    )


@router.post("/app/appointments/{appointment_id}/edit")
def edit_appointment_submit(
    appointment_id: int,
    starts_at: str = Form(...),
    duration_minutes: int = Form(30),
    status: str = Form(...),
    reason: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    schedule_agent: ScheduleAgent = Depends(get_schedule_agent),
):
    try:
        appointment = schedule_agent.update_appointment(
            db,
            appointment_id,
            AppointmentUpdate(
                starts_at=datetime.fromisoformat(starts_at),
                duration_minutes=duration_minutes,
                status=AppointmentStatus(status),
                reason=reason or None,
                notes=notes or None,
            ),
            actor=current_user.username,
        )
        return redirect_with_message(
            f"/app/appointments?selected_date={appointment.starts_at.date().isoformat()}",
            message="Turno actualizado",
        )
    except Exception as exc:
        return redirect_with_message(f"/app/appointments/{appointment_id}/edit", error=str(exc))


@router.get("/app/patients", response_class=HTMLResponse)
def patients_page(
    request: Request,
    query: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    reception_agent: ReceptionAgent = Depends(get_reception_agent),
):
    patients = filter_patients_collection(reception_agent.list_patients(db), query)
    return render_admin(
        request,
        template_name="admin_patients.html",
        current_user=current_user,
        page_title="Pacientes",
        page_subtitle="Gestion manual secundaria. El alta principal vive en la web publica.",
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
    reception_agent: ReceptionAgent = Depends(get_reception_agent),
):
    try:
        reception_agent.create_patient(
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
        return redirect_with_message("/app/patients", message="Paciente creado manualmente")
    except Exception as exc:
        return redirect_with_message("/app/patients", error=str(exc))


@router.post("/app/patients/{patient_id}/delete")
def delete_patient_from_admin(
    patient_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    reception_agent: ReceptionAgent = Depends(get_reception_agent),
):
    try:
        reception_agent.delete_patient(db, patient_id, actor=current_user.username)
        return redirect_with_message("/app/patients", message="Paciente eliminado")
    except Exception as exc:
        return redirect_with_message("/app/patients", error=str(exc))


@router.get("/app/patients/{patient_id}/edit", response_class=HTMLResponse)
def edit_patient_page(
    request: Request,
    patient_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    reception_agent: ReceptionAgent = Depends(get_reception_agent),
):
    patient = reception_agent.get_patient(db, patient_id)
    return render_admin(
        request,
        template_name="admin_patient_edit.html",
        current_user=current_user,
        page_title="Editar paciente",
        page_subtitle="Mantenimiento manual puntual, sin invadir el dashboard.",
        active_page="patients",
        patient=patient,
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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    reception_agent: ReceptionAgent = Depends(get_reception_agent),
):
    try:
        reception_agent.update_patient(
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
            ),
            actor=current_user.username,
        )
        return redirect_with_message("/app/patients", message="Paciente actualizado")
    except Exception as exc:
        return redirect_with_message(f"/app/patients/{patient_id}/edit", error=str(exc))


@router.get("/app/professionals", response_class=HTMLResponse)
def professionals_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    professional_service: ProfessionalService = Depends(get_professional_service),
    schedule_agent: ScheduleAgent = Depends(get_schedule_agent),
):
    ensure_admin(current_user)
    professionals = professional_service.list_professionals(db)
    availability_windows = schedule_agent.list_availability_windows(db, date_from=date.today())
    windows_count = defaultdict(int)
    for row in availability_windows:
        windows_count[row.professional_id] += 1
    return render_admin(
        request,
        template_name="admin_professionals.html",
        current_user=current_user,
        page_title="Profesionales",
        page_subtitle="Altas administrativas ocasionales y estado general del staff.",
        active_page="professionals",
        professionals=professionals,
        windows_count=windows_count,
    )


@router.post("/app/professionals")
def create_professional_from_admin(
    first_name: str = Form(...),
    last_name: str = Form(...),
    specialty: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    default_appointment_duration: int = Form(30),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    professional_service: ProfessionalService = Depends(get_professional_service),
):
    ensure_admin(current_user)
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
            ),
            actor=current_user.username,
        )
        return redirect_with_message("/app/professionals", message="Profesional creado")
    except Exception as exc:
        return redirect_with_message("/app/professionals", error=str(exc))


@router.get("/app/professionals/{professional_id}/edit", response_class=HTMLResponse)
def edit_professional_page(
    request: Request,
    professional_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    professional_service: ProfessionalService = Depends(get_professional_service),
):
    ensure_admin(current_user)
    professional = professional_service.get_professional(db, professional_id)
    return render_admin(
        request,
        template_name="admin_professional_edit.html",
        current_user=current_user,
        page_title="Editar profesional",
        page_subtitle="Mantenimiento administrativo puntual del staff clínico.",
        active_page="professionals",
        professional=professional,
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
    is_active: bool = Form(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    professional_service: ProfessionalService = Depends(get_professional_service),
):
    ensure_admin(current_user)
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
                is_active=is_active,
            ),
            actor=current_user.username,
        )
        return redirect_with_message("/app/professionals", message="Profesional actualizado")
    except Exception as exc:
        return redirect_with_message(f"/app/professionals/{professional_id}/edit", error=str(exc))


@router.post("/app/professionals/{professional_id}/delete")
def delete_professional_from_admin(
    professional_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    professional_service: ProfessionalService = Depends(get_professional_service),
):
    ensure_admin(current_user)
    try:
        professional_service.delete_professional(db, professional_id, actor=current_user.username)
        return redirect_with_message("/app/professionals", message="Profesional eliminado")
    except Exception as exc:
        return redirect_with_message("/app/professionals", error=str(exc))


@router.get("/app/settings", response_class=HTMLResponse)
def settings_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    professional_service: ProfessionalService = Depends(get_professional_service),
    schedule_agent: ScheduleAgent = Depends(get_schedule_agent),
    followup_agent: FollowUpAgent = Depends(get_followup_agent),
):
    ensure_admin(current_user)
    professionals = active_professionals(db, professional_service)
    availability_windows = schedule_agent.list_availability_windows(db, date_from=date.today())
    grouped_windows = defaultdict(list)
    for row in availability_windows:
        grouped_windows[row.professional_id].append(row)

    notifications = followup_agent.list_notifications(db)
    notification_summary = {
        "pending": len([item for item in notifications if item.status == NotificationStatus.PENDING]),
        "sent": len([item for item in notifications if item.status == NotificationStatus.SENT]),
        "failed": len([item for item in notifications if item.status == NotificationStatus.FAILED]),
    }
    return render_admin(
        request,
        template_name="admin_settings.html",
        current_user=current_user,
        page_title="Configuracion",
        page_subtitle="Disponibilidad puntual por fecha y motor de seguimiento.",
        active_page="settings",
        professionals=professionals,
        grouped_windows=grouped_windows,
        notification_summary=notification_summary,
        smtp_configured=followup_agent.email_client.is_configured(),
        smtp_sender=followup_agent.settings.email_from,
        reminder_hours_ahead=followup_agent.settings.reminder_hours_ahead,
    )


@router.post("/app/settings/availability-windows")
def create_availability_window_from_admin(
    professional_id: int = Form(...),
    availability_date: str = Form(...),
    start_time: str = Form(...),
    end_time: str = Form(...),
    slot_duration_minutes: int = Form(30),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    schedule_agent: ScheduleAgent = Depends(get_schedule_agent),
):
    ensure_admin(current_user)
    try:
        schedule_agent.create_availability_window(
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
        return redirect_with_message("/app/settings", message="Disponibilidad guardada")
    except Exception as exc:
        return redirect_with_message("/app/settings", error=str(exc))


@router.post("/app/settings/availability-windows/{availability_window_id}/delete")
def delete_availability_window_from_admin(
    availability_window_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    schedule_agent: ScheduleAgent = Depends(get_schedule_agent),
):
    ensure_admin(current_user)
    try:
        schedule_agent.delete_availability_window(db, availability_window_id, actor=current_user.username)
        return redirect_with_message("/app/settings", message="Disponibilidad eliminada")
    except Exception as exc:
        return redirect_with_message("/app/settings", error=str(exc))


@router.post("/app/notifications/prepare")
def prepare_reminders_from_admin(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    followup_agent: FollowUpAgent = Depends(get_followup_agent),
):
    ensure_admin(current_user)
    prepared = followup_agent.prepare_upcoming_reminders(db, actor=current_user.username)
    return redirect_with_message("/app/settings", message=f"Recordatorios preparados: {prepared}")


@router.post("/app/notifications/send")
def send_notifications_from_admin(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    followup_agent: FollowUpAgent = Depends(get_followup_agent),
):
    ensure_admin(current_user)
    result = followup_agent.send_pending_notifications(db, actor=current_user.username)
    return redirect_with_message("/app/settings", message=f"Enviados: {result['sent']}, omitidos: {result['skipped']}")
