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
from app.services.followup_service import FollowUpService
from app.services.payment_service import PaymentService
from app.services.schedule_service import ScheduleService

logger = logging.getLogger(__name__)


def run(followup_service: FollowUpService | None = None) -> dict:
    settings = get_settings()
    followup_service = followup_service or FollowUpService(settings, EmailClient(settings), WhatsAppClient(settings))
    schedule_service = ScheduleService(settings)
    # Expiring holds never talks to the payment provider, so no gateway is needed here.
    payment_service = PaymentService(settings, None, schedule_service, followup_service)

    db = db_session.SessionLocal()
    try:
        expired = payment_service.expire_unpaid(db)
        prepared = followup_service.prepare_upcoming_reminders(db, actor="scheduler")
        dispatched = followup_service.send_pending_notifications(db, limit=500, actor="scheduler")
    finally:
        db.close()
    return {"expired_holds": expired, "reminders_prepared": prepared, **dispatched}


def main() -> None:
    settings = get_settings()
    configure_logging(settings.debug, json_format=settings.log_format == "json", project_id=settings.google_cloud_project)
    summary = run()
    logger.info("Scheduled run finished: %s", summary)
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
