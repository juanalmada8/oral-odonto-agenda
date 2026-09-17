import json

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog


def _jsonable(details: dict | None) -> dict | None:
    """`details` va a una columna JSON, y ahí no entran Decimal, date ni Enum.

    Se normaliza acá y no en cada llamador: una auditoría nunca puede ser el motivo
    de que falle la operación que está registrando.
    """
    if details is None:
        return None
    return json.loads(json.dumps(details, default=str))


def create_audit_log(
    db: Session,
    *,
    action: str,
    entity_name: str,
    entity_id: str,
    actor: str = "system",
    description: str | None = None,
    details: dict | None = None,
) -> AuditLog:
    log = AuditLog(
        action=action,
        entity_name=entity_name,
        entity_id=entity_id,
        actor=actor,
        description=description,
        details=_jsonable(details),
    )
    db.add(log)
    return log
