from app.api.deps import get_followup_agent
from app.db.session import SessionLocal


def main() -> None:
    db = SessionLocal()
    try:
        followup_agent = get_followup_agent()
        prepared = followup_agent.prepare_upcoming_reminders(db)
        result = followup_agent.send_pending_notifications(db)
        print(
            {
                "prepared": prepared,
                "sent": result["sent"],
                "skipped": result["skipped"],
            }
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
