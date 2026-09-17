"""Send due notifications outside the request that queued them."""

import logging

from app.db import session as db_session
from app.services.followup_agent import FollowUpAgent

logger = logging.getLogger(__name__)


def dispatch_due_notifications(followup_agent: FollowUpAgent, limit: int = 20) -> dict[str, int]:
    """Background task: flush the outbox right after a request (the scheduled job retries later)."""
    db = db_session.SessionLocal()
    try:
        return followup_agent.send_pending_notifications(db, limit=limit, actor="dispatcher")
    except Exception:
        logger.exception("Background notification dispatch failed")
        db.rollback()
        return {}
    finally:
        db.close()
