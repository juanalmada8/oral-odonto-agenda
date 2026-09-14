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
# its slot while its hold has not expired (see ScheduleAgent._blocking_filter).
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
    PAYMENT_LINK = "payment_link"
    CUSTOM = "custom"


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
