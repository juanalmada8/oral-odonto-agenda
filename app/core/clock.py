"""Single source of "now" for business rules, in the clinic's local timezone.

Appointments are stored as naive datetimes expressed in APP_TIMEZONE, so every comparison
against them must go through this module instead of datetime.now()/date.today(), which
follow the server clock (UTC on Cloud Run). Tests freeze time by monkeypatching `now`.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.core.config import get_settings


def now() -> datetime:
    tz = ZoneInfo(get_settings().app_timezone)
    return datetime.now(tz).replace(tzinfo=None, microsecond=0)


def today() -> date:
    return now().date()


def to_aware(value: datetime) -> datetime:
    """Attach the clinic timezone to a naive local datetime (needed by external APIs)."""
    return value.replace(tzinfo=ZoneInfo(get_settings().app_timezone))
