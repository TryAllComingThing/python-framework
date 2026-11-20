"""Application-owned JSON logger; does not replace third-party/root handlers."""

import json
import logging
from datetime import datetime, timezone
from typing import TextIO

from app.common.redaction import redact


class FrameworkStreamHandler(logging.StreamHandler[TextIO]):
    """Marker subclass so repeated logging setup is idempotent."""

    _framework_handler = True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for name in ("request_id", "event", "fields"):
            if hasattr(record, name):
                payload[name] = getattr(record, name)
        return json.dumps(redact(payload), ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger("python_framework")
    logger.setLevel(level.upper())
    logger.propagate = False
    if not any(getattr(h, "_framework_handler", False) for h in logger.handlers):
        handler = FrameworkStreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    return logger
