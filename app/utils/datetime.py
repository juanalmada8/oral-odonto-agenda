from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


def ensure_local_naive(value: datetime, timezone_name: str) -> datetime:
    if value.tzinfo is None:
        return value.replace(microsecond=0)
    localized = value.astimezone(ZoneInfo(timezone_name))
    return localized.replace(tzinfo=None, microsecond=0)


def combine_date_time(day: date, value: time) -> datetime:
    return datetime.combine(day, value)


def date_range_start(day: date) -> datetime:
    return datetime.combine(day, time.min)


def date_range_end(day: date) -> datetime:
    return datetime.combine(day, time.max)


def calculate_end(starts_at: datetime, duration_minutes: int) -> datetime:
    return starts_at + timedelta(minutes=duration_minutes)
