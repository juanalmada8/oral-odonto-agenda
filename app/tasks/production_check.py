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

    def problem(message: str) -> None:
        (errors if in_production else warnings).append(message)

    if not settings.public_base_url.startswith("https://"):
        problem("PUBLIC_BASE_URL debe ser https:// (links de emails y callbacks de Mercado Pago).")
    if settings.deposit_default_amount > 0 and not settings.mercadopago_access_token:
        problem("Hay seña por defecto pero falta MERCADOPAGO_ACCESS_TOKEN.")
    if settings.mercadopago_access_token and not settings.mercadopago_webhook_secret:
        warnings.append("Falta MERCADOPAGO_WEBHOOK_SECRET: las notificaciones de pago no se validan con firma.")
    if settings.mercadopago_access_token and settings.mercadopago_access_token.startswith("TEST-") and in_production:
        warnings.append("MERCADOPAGO_ACCESS_TOKEN es de prueba (TEST-): no se cobra dinero real.")
    whatsapp_fields = {
        "WHATSAPP_ACCESS_TOKEN": settings.whatsapp_access_token,
        "WHATSAPP_PHONE_NUMBER_ID": settings.whatsapp_phone_number_id,
        "WHATSAPP_APP_SECRET": settings.whatsapp_app_secret,
        "WHATSAPP_VERIFY_TOKEN": settings.whatsapp_verify_token,
    }
    missing_whatsapp = [name for name, value in whatsapp_fields.items() if not value]
    if len(missing_whatsapp) == len(whatsapp_fields):
        warnings.append("WhatsApp sin configurar: los recordatorios salen solo por email.")
    elif missing_whatsapp:
        problem(f"WhatsApp configurado a medias, faltan: {', '.join(missing_whatsapp)}.")
    if in_production and not settings.trust_proxy_headers:
        warnings.append("TRUST_PROXY_HEADERS=false: detrás de Cloud Run el rate limit vería la IP del balanceador.")

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


def _redact(url: str) -> str:
    """Hide the password when printing connection strings."""
    scheme, _, rest = url.partition("://")
    if "@" not in rest:
        return url
    credentials, _, host = rest.rpartition("@")
    user = credentials.split(":", 1)[0]
    return f"{scheme}://{user}:***@{host}"


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
    print(f"DATABASE_URL={_redact(settings.database_url)}")

    _print_lines("\nAdvertencias:", warnings)
    _print_lines("\nErrores:", errors)

    if errors:
        print("\nResultado: FAIL")
        sys.exit(1)

    print("\nResultado: OK")


if __name__ == "__main__":
    main()
