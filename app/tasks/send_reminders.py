"""Backwards-compatible entry point; the scheduled job now does holds, reminders and retries."""

from app.tasks.run_scheduled import main

if __name__ == "__main__":
    main()
