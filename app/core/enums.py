from enum import Enum


class AppointmentStatus(str, Enum):
    PENDING_PAYMENT = "pending_payment"
    RESERVED = "reserved"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    NO_SHOW = "no_show"
    EXPIRED = "expired"


# States that occupy the professional's calendar. A pending_payment appointment only blocks
# its slot while its hold has not expired (see ScheduleService._blocking_filter).
BLOCKING_APPOINTMENT_STATUSES = (
    AppointmentStatus.PENDING_PAYMENT,
    AppointmentStatus.RESERVED,
    AppointmentStatus.CONFIRMED,
    AppointmentStatus.COMPLETED,
    AppointmentStatus.NO_SHOW,
)

# States where the patient is still expected to attend.
UPCOMING_APPOINTMENT_STATUSES = (
    AppointmentStatus.PENDING_PAYMENT,
    AppointmentStatus.RESERVED,
    AppointmentStatus.CONFIRMED,
)

APPOINTMENT_STATUS_LABELS = {
    AppointmentStatus.PENDING_PAYMENT: "Seña pendiente",
    AppointmentStatus.RESERVED: "Reservado",
    AppointmentStatus.CONFIRMED: "Confirmado",
    AppointmentStatus.CANCELLED: "Cancelado",
    AppointmentStatus.COMPLETED: "Atendido",
    AppointmentStatus.NO_SHOW: "Ausente",
    AppointmentStatus.EXPIRED: "Vencido",
}


class NotificationChannel(str, Enum):
    EMAIL = "email"
    WHATSAPP = "whatsapp"


class NotificationStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"


class NotificationType(str, Enum):
    CONFIRMATION = "confirmation"
    REMINDER = "reminder"
    CANCELLATION = "cancellation"
    RESCHEDULE = "reschedule"
    WAITLIST = "waitlist"
    PAYMENT_LINK = "payment_link"
    CUSTOM = "custom"
    # Avisos a quien atiende (no al paciente). La columna es VARCHAR(20): valores de hasta 20 caracteres.
    PROFESSIONAL_NEW = "professional_new"
    PROFESSIONAL_CANCEL = "professional_cancel"
    PROFESSIONAL_MOVE = "professional_move"
    PROFESSIONAL_DIGEST = "professional_digest"


class PaymentStatus(str, Enum):
    PENDING = "pending"
    IN_PROCESS = "in_process"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"
    EXPIRED = "expired"


PAYMENT_STATUS_LABELS = {
    PaymentStatus.PENDING: "Pendiente",
    PaymentStatus.IN_PROCESS: "En proceso",
    PaymentStatus.APPROVED: "Aprobado",
    PaymentStatus.REJECTED: "Rechazado",
    PaymentStatus.CANCELLED: "Cancelado",
    PaymentStatus.REFUNDED: "Devuelto",
    PaymentStatus.EXPIRED: "Vencido",
}


class UserRole(str, Enum):
    ADMIN = "admin"
    RECEPTIONIST = "receptionist"
    PROFESSIONAL = "professional"


ROLE_LABELS = {
    UserRole.ADMIN: "Administración",
    UserRole.RECEPTIONIST: "Recepción",
    UserRole.PROFESSIONAL: "Profesional",
}


class WaitlistPeriod(str, Enum):
    ANY = "any"
    MORNING = "morning"
    AFTERNOON = "afternoon"


class WaitlistStatus(str, Enum):
    WAITING = "waiting"
    NOTIFIED = "notified"
    BOOKED = "booked"
    CANCELLED = "cancelled"


WAITLIST_PERIOD_LABELS = {
    WaitlistPeriod.ANY: "Cualquier horario",
    WaitlistPeriod.MORNING: "Mañana",
    WaitlistPeriod.AFTERNOON: "Tarde",
}

WAITLIST_STATUS_LABELS = {
    WaitlistStatus.WAITING: "Esperando",
    WaitlistStatus.NOTIFIED: "Avisado",
    WaitlistStatus.BOOKED: "Reservó",
    WaitlistStatus.CANCELLED: "Dado de baja",
}


NOTIFICATION_TYPE_LABELS = {
    NotificationType.CONFIRMATION: "Confirmación",
    NotificationType.REMINDER: "Recordatorio",
    NotificationType.CANCELLATION: "Cancelación",
    NotificationType.RESCHEDULE: "Reprogramación",
    NotificationType.WAITLIST: "Lista de espera",
    NotificationType.PAYMENT_LINK: "Link de pago",
    NotificationType.CUSTOM: "Otro",
    NotificationType.PROFESSIONAL_NEW: "Turno nuevo (al profesional)",
    NotificationType.PROFESSIONAL_CANCEL: "Cancelación (al profesional)",
    NotificationType.PROFESSIONAL_MOVE: "Cambio de horario (al profesional)",
    NotificationType.PROFESSIONAL_DIGEST: "Agenda de mañana (al profesional)",
}
