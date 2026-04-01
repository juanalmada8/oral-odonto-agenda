from __future__ import annotations

from collections.abc import Sequence
import sys

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings, get_settings


def _check_settings(settings: Settings) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    in_production = settings.app_env.lower() == "production"

    if not in_production:
        warnings.append("APP_ENV no está en 'production'.")
    if settings.debug:
        if in_production:
            errors.append("DEBUG está en true; para producción debe estar en false.")
        else:
            warnings.append("DEBUG está en true; para producción debe estar en false.")

    if settings.secret_key == "change-me":
        if in_production:
            errors.append("SECRET_KEY sigue con valor por defecto.")
        else:
            warnings.append("SECRET_KEY sigue con valor por defecto.")
    if len(settings.secret_key) < 32:
        if in_production:
            errors.append("SECRET_KEY debe tener al menos 32 caracteres.")
        else:
            warnings.append("SECRET_KEY debería tener al menos 32 caracteres para producción.")

    if not settings.database_url.startswith("postgresql"):
        if in_production:
            errors.append("DATABASE_URL debe apuntar a PostgreSQL en producción.")
        else:
            warnings.append("DATABASE_URL no usa PostgreSQL.")

    if not settings.smtp_host:
        warnings.append("SMTP_HOST vacío: no se podrán enviar emails.")
    if not settings.email_from:
        warnings.append("EMAIL_FROM vacío: faltará remitente para notificaciones.")

    return errors, warnings


def _check_database(database_url: str) -> list[str]:
    errors: list[str] = []
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, future=True, pool_pre_ping=True, connect_args=connect_args)

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            try:
                conn.execute(text("SELECT version_num FROM alembic_version"))
            except SQLAlchemyError:
                errors.append("No existe tabla alembic_version o no se puede leer. Ejecutá 'alembic upgrade head'.")
    except SQLAlchemyError as exc:
        errors.append(f"No se pudo conectar a la base de datos: {exc}")
    finally:
        engine.dispose()

    return errors


def _print_lines(title: str, lines: Sequence[str]) -> None:
    if not lines:
        return
    print(title)
    for line in lines:
        print(f"- {line}")


def main() -> None:
    try:
        settings = get_settings()
    except Exception as exc:  # pragma: no cover
        print("ERROR: configuración inválida.")
        print(f"- {exc}")
        sys.exit(1)

    errors, warnings = _check_settings(settings)
    errors.extend(_check_database(settings.database_url))

    print("Chequeo de producción ORAL")
    print(f"APP_ENV={settings.app_env}")
    print(f"DEBUG={settings.debug}")
    print(f"DATABASE_URL={settings.database_url}")

    _print_lines("\nAdvertencias:", warnings)
    _print_lines("\nErrores:", errors)

    if errors:
        print("\nResultado: FAIL")
        sys.exit(1)

    print("\nResultado: OK")


if __name__ == "__main__":
    main()
