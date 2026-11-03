"""Structured JSON logging with correlation IDs and secret redaction."""
import contextvars
import json
import logging
import re
import sys
from datetime import UTC, datetime

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)

_SENSITIVE_KEYS = re.compile(r"(authorization|password|secret|token|api[_-]?key|cookie)", re.I)
_BEARER = re.compile(r"(?i)bearer\s+[a-z0-9._\-]+")
_RESERVED = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}


def _redact(key: str, value: object) -> object:
    if _SENSITIVE_KEYS.search(key):
        return "[REDACTED]"
    if isinstance(value, str):
        return _BEARER.sub("Bearer [REDACTED]", value)
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": _BEARER.sub("Bearer [REDACTED]", record.getMessage()),
            "request_id": request_id_var.get(),
        }
        for k, v in record.__dict__.items():
            if k not in _RESERVED and not k.startswith("_"):
                payload[k] = _redact(k, v)
        if record.exc_info:
            payload["exc_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    logging.getLogger("uvicorn.access").disabled = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"vand.{name}")
