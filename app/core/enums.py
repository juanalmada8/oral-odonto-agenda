from enum import Enum


class AppointmentStatus(str, Enum):
    RESERVED = "reserved"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


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
    CUSTOM = "custom"


class UserRole(str, Enum):
    ADMIN = "admin"
    RECEPTIONIST = "receptionist"
