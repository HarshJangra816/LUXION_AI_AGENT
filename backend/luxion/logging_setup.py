"""Structured logging for Luxion.

Provides:
- JSON (or plain text) log formatting
- Console + rotating file handlers
- Secret redaction so credentials never land in logs
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from typing import Any

from luxion.config.settings import LoggingConfig

_SENSITIVE_KEY_RE = re.compile(
    r"(api[_-]?key|password|passwd|secret|token|authorization|credential)", re.IGNORECASE
)
_SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(sk|pk|rk)-[A-Za-z0-9_\-]{8,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{8,}\b"),
    re.compile(r"(?i)\b(api[_-]?key|token|password|secret)\b(\s*[=:]\s*)(\S+)"),
]

_STANDARD_ATTRS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}


def redact(text: str) -> str:
    """Mask credential-looking material inside free text."""
    out = text
    out = _SECRET_PATTERNS[0].sub("***REDACTED***", out)
    out = _SECRET_PATTERNS[1].sub("Bearer ***REDACTED***", out)
    out = _SECRET_PATTERNS[2].sub(lambda m: f"{m.group(1)}{m.group(2)}***REDACTED***", out)
    return out


class RedactionFilter(logging.Filter):
    """Scrubs secrets from messages and sensitive ``extra`` fields."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: self._scrub(k, v) for k, v in record.args.items()}
            else:
                record.args = tuple(self._scrub("", a) for a in record.args)
        for key, value in list(record.__dict__.items()):
            if key not in _STANDARD_ATTRS:
                record.__dict__[key] = self._scrub(key, value)
        return True

    @staticmethod
    def _scrub(key: str, value: Any) -> Any:
        if _SENSITIVE_KEY_RE.search(key) and isinstance(value, str):
            return "***REDACTED***"
        if isinstance(value, str):
            return redact(value)
        return value


class JsonFormatter(logging.Formatter):
    """One JSON object per line with all non-standard record fields included."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and key != "msg":
                if isinstance(value, (str, int, float, bool, type(None))):
                    payload[key] = value
                else:
                    payload[key] = str(value)
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))
        try:
            return json.dumps(payload, ensure_ascii=False)
        except (TypeError, ValueError):
            return json.dumps(
                {"ts": payload["ts"], "level": payload["level"], "msg": str(record.msg)}
            )


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extras = {
            k: v for k, v in record.__dict__.items() if k not in _STANDARD_ATTRS and k != "msg"
        }
        if extras:
            suffix = " ".join(f"{k}={v}" for k, v in extras.items())
            return f"{base} | {suffix}"
        return base


_configured = False


def configure_logging(config: LoggingConfig, *, logs_dir, force: bool = False) -> None:
    """Install Luxion log handlers on the root logger. Idempotent unless ``force``."""
    global _configured
    if _configured and not force:
        return

    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    level = getattr(logging, config.level.upper(), logging.INFO)
    root.setLevel(level)
    formatter: logging.Formatter
    if config.json_logs:
        formatter = JsonFormatter()
    else:
        formatter = TextFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")

    redaction = RedactionFilter()

    if config.console:
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(formatter)
        console.addFilter(redaction)
        root.addHandler(console)

    if logs_dir is not None:
        file_handler = RotatingFileHandler(
            logs_dir / config.file_name,
            maxBytes=config.max_bytes,
            backupCount=config.backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(redaction)
        root.addHandler(file_handler)

    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
