"""Normalizers for personal data typed by patients and staff.

Validators raise ValueError with Spanish, patient-facing messages; pydantic surfaces them as-is.
"""

import re
import unicodedata
from decimal import Decimal, InvalidOperation

import phonenumbers

NAME_PATTERN = re.compile(r"^[^\W\d_]+(?:[ '\-.][^\W\d_]+)*\.?$", re.UNICODE)


def normalize_dni(value: str, *, strict: bool) -> str:
    """Argentine DNI: 7-8 digits (dots and spaces allowed when typing).

    Staff may register foreign documents, so non-strict mode accepts 6-20 alphanumerics.
    """
    cleaned = re.sub(r"[\s.\-]", "", value or "").upper()
    if strict:
        if not re.fullmatch(r"\d{7,8}", cleaned):
            raise ValueError("Ingresá un DNI válido: 7 u 8 números, sin puntos.")
        return cleaned
    if not re.fullmatch(r"[0-9A-Z]{6,20}", cleaned):
        raise ValueError("Ingresá un documento válido (6 a 20 letras o números).")
    return cleaned


def normalize_person_name(value: str, *, label: str = "El nombre") -> str:
    cleaned = re.sub(r"\s+", " ", (value or "").strip())
    if len(cleaned) < 2:
        raise ValueError(f"{label} debe tener al menos 2 letras.")
    if len(cleaned) > 80:
        raise ValueError(f"{label} no puede superar los 80 caracteres.")
    if not NAME_PATTERN.fullmatch(cleaned):
        raise ValueError(f"{label} solo puede tener letras, espacios, apóstrofes o guiones.")
    return cleaned


def normalize_mobile_phone(value: str) -> str:
    """Return a WhatsApp-ready E.164 number (+549... for Argentine mobiles).

    Argentines usually type their cell phone without the mobile "9" (e.g. "11 5555-5555"),
    which parses as a landline; in a field labelled "Celular" we add it back.
    """
    raw = (value or "").strip()
    error = "Ingresá un celular válido con código de área (ej: 11 5555-5555)."
    if not raw:
        raise ValueError(error)
    try:
        number = phonenumbers.parse(raw, "AR")
    except phonenumbers.NumberParseException as exc:
        raise ValueError(error) from exc
    if not phonenumbers.is_valid_number(number):
        raise ValueError(error)
    if number.country_code == 54 and not str(number.national_number).startswith("9"):
        mobile = phonenumbers.parse(f"+549{number.national_number}")
        if phonenumbers.is_valid_number(mobile) and phonenumbers.number_type(mobile) == phonenumbers.PhoneNumberType.MOBILE:
            number = mobile
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)


def format_phone_for_display(value: str | None) -> str:
    if not value:
        return ""
    try:
        return phonenumbers.format_number(phonenumbers.parse(value, "AR"), phonenumbers.PhoneNumberFormat.INTERNATIONAL)
    except phonenumbers.NumberParseException:
        return value


def fold_text(value: str) -> str:
    """Lowercase, accent-free, letters-only form used to compare names typed differently."""
    decomposed = unicodedata.normalize("NFKD", value or "")
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"[^a-z ]", "", without_marks.casefold()).strip()


def names_match(stored: str, provided: str) -> bool:
    """True when both last names share at least one word (handles compound surnames and accents)."""
    stored_words = set(fold_text(stored).split())
    provided_words = set(fold_text(provided).split())
    return bool(stored_words & provided_words)


def parse_money(value: str | None) -> Decimal | None:
    """Parse amounts typed Argentine-style ("10.000", "10000,50", "$ 8.500"). Blank means None."""
    cleaned = re.sub(r"[\s$]", "", value or "")
    if not cleaned:
        return None
    if "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", cleaned):
        cleaned = cleaned.replace(".", "")
    try:
        amount = Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError("Ingresá un monto válido (ej: 10000).") from exc
    if not amount.is_finite():
        raise ValueError("Ingresá un monto válido (ej: 10000).")
    if amount < 0:
        raise ValueError("El monto no puede ser negativo.")
    return amount.quantize(Decimal("0.01"))
