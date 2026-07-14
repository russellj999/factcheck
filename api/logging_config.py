"""
logging_config.py — structured JSON logging setup.

Every log record emitted through this logger automatically includes
`ingest_id` and `verify_job_id` when they are set on the context var.
"""
import logging
import json
import traceback
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Optional

# Context variables — set per-request in middleware / per-job in worker
ingest_id_var: ContextVar[Optional[str]] = ContextVar("ingest_id", default=None)
verify_job_id_var: ContextVar[Optional[str]] = ContextVar("verify_job_id", default=None)


class JsonFormatter(logging.Formatter):
    """Emit log records as single-line JSON with correlation IDs injected."""

    def format(self, record: logging.LogRecord) -> str:  # noqa: A003
        payload: dict = {
            "ts": datetime.now(tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "ingest_id": ingest_id_var.get(),
            "verify_job_id": verify_job_id_var.get(),
        }
        if record.exc_info:
            payload["exception"] = traceback.format_exception(*record.exc_info)
        return json.dumps(payload)


def configure_logging(level: str = "INFO") -> None:
    """Call once at application startup."""
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
