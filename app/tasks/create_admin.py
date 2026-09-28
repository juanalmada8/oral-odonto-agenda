"""Crea el primer usuario administrador, sin datos de demostración.

Es el arranque de una instalación productiva: `seed_demo` sirve para probar, pero mete
profesionales y pacientes inventados que después hay que borrar a mano.

Se ejecuta como job (ver docs/DEPLOYMENT.md):

    ADMIN_USERNAME=maria ADMIN_PASSWORD='...' ADMIN_FULL_NAME='María Pérez' \
    ADMIN_EMAIL=maria@consultorio.com odonto-create-admin

Es idempotente: si el usuario ya existe no lo toca ni cambia su contraseña, así que
volver a correr el job (algo que Cloud Run hace ante un reintento) no rompe nada.
"""

import logging
import os
import sys

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.enums import UserRole
from app.core.logging import configure_logging
from app.db.session import SessionLocal
from app.models.user import User
from app.schemas.auth import UserCreate
from app.services.auth_service import AuthService

logger = logging.getLogger(__name__)

REQUERIDAS = ("ADMIN_USERNAME", "ADMIN_PASSWORD", "ADMIN_FULL_NAME", "ADMIN_EMAIL")


def main() -> int:
    configure_logging()
    faltantes = [nombre for nombre in REQUERIDAS if not os.environ.get(nombre)]
    if faltantes:
        logger.error("Faltan variables de entorno: %s", ", ".join(faltantes))
        return 2

    try:
        payload = UserCreate(
            username=os.environ["ADMIN_USERNAME"],
            full_name=os.environ["ADMIN_FULL_NAME"],
            email=os.environ["ADMIN_EMAIL"],
            password=os.environ["ADMIN_PASSWORD"],
            role=UserRole.ADMIN,
        )
    except ValueError as exc:
        # La contraseña nunca se escribe en el log.
        logger.error("Los datos del administrador no son válidos: %s", str(exc).replace(os.environ["ADMIN_PASSWORD"], "***"))
        return 2

    with SessionLocal() as db:
        existente = db.scalar(
            select(User).where(func.lower(User.username) == payload.username)
        )
        if existente:
            logger.info("El usuario %s ya existe: no se modifica.", payload.username)
            return 0

        total_admins = db.scalar(
            select(func.count(User.id)).where(User.role == UserRole.ADMIN).where(User.is_active.is_(True))
        )
        AuthService(get_settings()).create_user(db, payload, actor="create_admin")
        logger.info(
            "Administrador %s creado (ya había %s administrador(es) activo(s)).",
            payload.username,
            total_admins,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
