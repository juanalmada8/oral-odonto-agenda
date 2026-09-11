"""Periodic job (every ~10 minutes; Cloud Scheduler -> Cloud Run Job in production).

1. Expire unpaid booking holds and free their slots.
2. Queue reminders for appointments entering the reminder window.
3. Send (and retry) every due notification.
"""

import json
import logging

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db import session as db_session
from app.integrations.email import EmailClient
from app.integrations.whatsapp import WhatsAppClient
from app.services.followup_agent import FollowUpAgent
from app.services.payment_service import PaymentService
from app.services.schedule_agent import ScheduleAgent

logger = logging.getLogger(__name__)


def run(followup_agent: FollowUpAgent | None = None) -> dict:
    settings = get_settings()
    followup_agent = followup_agent or FollowUpAgent(settings, EmailClient(settings), WhatsAppClient(settings))
    schedule_agent = ScheduleAgent(settings)
    # Expiring holds never talks to the payment provider, so no gateway is needed here.
    payment_service = PaymentService(settings, None, schedule_agent, followup_agent)

    db = db_session.SessionLocal()
    try:
        expired = payment_service.expire_unpaid(db)
        prepared = followup_agent.prepare_upcoming_reminders(db, actor="scheduler")
        dispatched = followup_agent.send_pending_notifications(db, limit=500, actor="scheduler")
    finally:
        db.close()
    return {"expired_holds": expired, "reminders_prepared": prepared, **dispatched}


def main() -> None:
    configure_logging(get_settings().debug)
    summary = run()
    logger.info("Scheduled run finished: %s", summary)
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
