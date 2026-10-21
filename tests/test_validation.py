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


def test_names_are_capitalized():
    assert normalize_person_name("juan martín") == "Juan Martín"
    assert normalize_person_name("ALMADA ORTIZ") == "Almada Ortiz"
    assert normalize_person_name("nazarena") == "Nazarena"
    assert normalize_person_name("j.") == "J."


def test_name_particles_stay_lowercase_except_first():
    assert normalize_person_name("maría de los ángeles") == "María de los Ángeles"
    assert normalize_person_name("de la fuente") == "De la Fuente"
    assert normalize_person_name("PEDRO Y PABLO") == "Pedro y Pablo"


def test_names_after_apostrophe_or_hyphen_are_capitalized():
    assert normalize_person_name("o'connor-díaz") == "O'Connor-Díaz"
    assert normalize_person_name("d'angelo") == "D'Angelo"


def test_mixed_case_names_are_kept():
    assert normalize_person_name("McDonald") == "McDonald"
    assert normalize_person_name("DiMaría") == "DiMaría"


def test_the_data_migration_capitalizes_like_the_app():
    """La migración lleva su propia copia de la regla (las migraciones no importan código de la app)."""
    import importlib.util
    from pathlib import Path

    path = next(Path("alembic/versions").glob("*_capitalize_names.py"))
    spec = importlib.util.spec_from_file_location("capitalize_names", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    for raw in ("juan martín", "ALMADA ORTIZ", "maría de los ángeles", "de la fuente", "o'connor-díaz", "McDonald", "j."):
        assert migration.capitalize_name(raw) == normalize_person_name(raw), raw


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
