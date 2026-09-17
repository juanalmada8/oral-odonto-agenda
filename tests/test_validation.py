import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.errors import humanize_validation_error
from app.schemas.booking import PublicBookingRequest
from app.utils.validation import names_match, normalize_dni, normalize_mobile_phone, normalize_person_name


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("11 5555-5555", "+5491155555555"),
        ("011 15 5555-5555", "+5491155555555"),
        ("+54 9 11 5555 5555", "+5491155555555"),
        ("351 555 1234", "+5493515551234"),
        ("+598 94 123 456", "+59894123456"),
    ],
)
def test_mobile_phone_normalization(raw, expected):
    assert normalize_mobile_phone(raw) == expected


@pytest.mark.parametrize("raw", ["15 5555 5555", "4555-5555", "123", "hola"])
def test_mobile_phone_rejects_incomplete_numbers(raw):
    with pytest.raises(ValueError, match="código de área"):
        normalize_mobile_phone(raw)


def test_dni_normalization():
    assert normalize_dni("30.555.111", strict=True) == "30555111"
    assert normalize_dni("7123456", strict=True) == "7123456"
    assert normalize_dni("AB123456", strict=False) == "AB123456"
    with pytest.raises(ValueError):
        normalize_dni("123", strict=True)
    with pytest.raises(ValueError):
        normalize_dni("AB123456", strict=True)


def test_person_name_rules():
    assert normalize_person_name("  María   José ") == "María José"
    assert normalize_person_name("O'Connor-Díaz") == "O'Connor-Díaz"
    with pytest.raises(ValueError):
        normalize_person_name("J")
    with pytest.raises(ValueError):
        normalize_person_name("R2D2")


def test_names_match_ignores_accents_case_and_compound_surnames():
    assert names_match("Fernández García", "fernandez")
    assert names_match("PEREZ", "Pérez")
    assert not names_match("Gomez", "Lopez")


def test_public_booking_requires_terms_and_contact():
    with pytest.raises(ValidationError) as exc:
        PublicBookingRequest(
            professional_id=1,
            starts_at="2026-03-30T09:00:00",
            dni="30555111",
            first_name="Ana",
            last_name="Perez",
            email="ana@example.com",
            phone="11 5555-5555",
            accept_terms=False,
        )
    assert "política de seña" in humanize_validation_error(exc.value)


def test_humanized_email_error_is_spanish():
    with pytest.raises(ValidationError) as exc:
        PublicBookingRequest(
            professional_id=1,
            starts_at="2026-03-30T09:00:00",
            dni="30555111",
            first_name="Ana",
            last_name="Perez",
            email="no-es-un-email",
            phone="11 5555-5555",
            accept_terms=True,
        )
    assert humanize_validation_error(exc.value).startswith("Email: ingresá un email válido")


@pytest.mark.parametrize(
    "url",
    ["postgres://u:p@host:5432/db", "postgresql://u:p@host:5432/db", "postgresql+psycopg://u:p@host:5432/db"],
)
def test_database_url_always_uses_psycopg3(url):
    settings = Settings(_env_file=None, database_url=url)
    assert settings.database_url == "postgresql+psycopg://u:p@host:5432/db"


def test_production_requires_secure_settings():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env="production", secret_key="short", database_url="postgresql://u:p@h/db")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env="production", secret_key="x" * 40, database_url="sqlite:///x.db")
