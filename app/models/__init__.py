"""SQLAlchemy models.

Importing any model imports this package, which registers every mapper. Relationships are
declared by class name ("WorkingHours"), so scripts that only import a couple of models
(seed, scheduled jobs) would otherwise fail with "failed to locate a name".
"""

from app.models.appointment import Appointment
from app.models.audit_log import AuditLog
from app.models.availability_window import AvailabilityWindow
from app.models.holiday_block import HolidayBlock
from app.models.notification import Notification
from app.models.patient import Patient
from app.models.professional import Professional
from app.models.user import User
from app.models.working_hours import WorkingHours

__all__ = [
    "Appointment",
    "AuditLog",
    "AvailabilityWindow",
    "HolidayBlock",
    "Notification",
    "Patient",
    "Professional",
    "User",
    "WorkingHours",
]
