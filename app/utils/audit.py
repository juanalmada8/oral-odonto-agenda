from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog


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
        details=details,
    )
    db.add(log)
    return log
