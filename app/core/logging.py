import json
import logging
from contextvars import ContextVar
from datetime import UTC, datetime
from logging.config import dictConfig

# Cloud Run sends "X-Cloud-Trace-Context"; logging it as the trace field groups a request's log lines.
trace_context: ContextVar[str | None] = ContextVar("trace_context", default=None)


class CloudLoggingFormatter(logging.Formatter):
    """One JSON object per line with the fields Google Cloud Logging understands (severity, trace)."""

    def __init__(self, project_id: str | None = None) -> None:
        super().__init__()
        self.project_id = project_id

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(),
        }
        trace = trace_context.get()
        if trace and self.project_id:
            entry["logging.googleapis.com/trace"] = f"projects/{self.project_id}/traces/{trace}"
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


def configure_logging(debug: bool = False, *, json_format: bool = False, project_id: str | None = None) -> None:
    level = "DEBUG" if debug else "INFO"
    formatter = (
        {"()": CloudLoggingFormatter, "project_id": project_id}
        if json_format
        else {"format": "%(asctime)s | %(levelname)s | %(name)s | %(message)s"}
    )
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {"default": formatter},
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                }
            },
            "root": {"handlers": ["console"], "level": level},
        }
    )
    for noisy in ("sqlalchemy.engine", "python_multipart", "httpcore", "asyncio"):
        logging.getLogger(noisy).setLevel("WARNING")
    # Uvicorn access logs duplicate Cloud Run's request logs.
    logging.getLogger("uvicorn.access").setLevel("WARNING" if json_format else "INFO")
