"""Spanish (Argentina) formatting shared by web pages, emails and WhatsApp messages."""

from datetime import date, datetime
from decimal import Decimal

DAY_LABELS = {
    0: "Lunes",
    1: "Martes",
    2: "Miércoles",
    3: "Jueves",
    4: "Viernes",
    5: "Sábado",
    6: "Domingo",
}
MONTH_LABELS = {
    1: "enero",
    2: "febrero",
    3: "marzo",
    4: "abril",
    5: "mayo",
    6: "junio",
    7: "julio",
    8: "agosto",
    9: "septiembre",
    10: "octubre",
    11: "noviembre",
    12: "diciembre",
}


def format_money(value: Decimal | int | float | None) -> str:
    """Argentine format: $ 12.500 (cents only when present)."""
    if value is None:
        return ""
    amount = Decimal(value).quantize(Decimal("0.01"))
    integer, _, cents = f"{amount:,.2f}".partition(".")
    integer = integer.replace(",", ".")
    return f"$ {integer}" if cents == "00" else f"$ {integer},{cents}"


def format_long_date(value: date | datetime | None) -> str:
    """'martes 31 de marzo'."""
    if value is None:
        return ""
    return f"{DAY_LABELS[value.weekday()].lower()} {value.day} de {MONTH_LABELS[value.month]}"


def format_short_date(value: date | datetime | None) -> str:
    """'Mar 31/03'."""
    if value is None:
        return ""
    return f"{DAY_LABELS[value.weekday()][:3]} {value:%d/%m}"


def mask_email(value: str | None) -> str:
    if not value or "@" not in value:
        return value or ""
    local, domain = value.split("@", 1)
    return f"{local[:1]}{'•' * max(1, min(len(local) - 1, 4))}@{domain}"
