"""Structured lifecycle logging for the RTAI backend.

Configuration is driven by the ``RTAI_LOG_LEVEL`` environment variable
(default ``INFO``).  Operational logs go to stderr so stdout stays reserved
for the server's own URL prints.  The formatter emits one human-readable
line per record::

    <UTC timestamp> <LEVEL> <logger> <event> key=value key=value

Privacy contract: application code must never log prompt text, assistant
deltas, file contents, tool arguments/results, permission contents, raw
streaming payloads, auth headers, cookies, credentials, environment
variable contents, or complete capability payloads.  This module provides
``short_id`` for safe correlation aliases and ``log_event`` for stable
event names; exception messages are treated as sensitive and logged only
as a category (``type(exc).__name__``).
"""

from __future__ import annotations

import logging
import logging.config
import os
import time
from typing import Any

LOG_LEVEL_ENV_KEY = "RTAI_LOG_LEVEL"
_VALID_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
_DEFAULT_LEVEL = "INFO"

#: Loggers owned by uvicorn.  They are configured with no handlers and
#: propagate to the root logger so their records share the same structured
#: format and are never duplicated by a second uvicorn config.
_UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access", "uvicorn.asgi")


class InvalidLogLevelError(ValueError):
    """Raised when ``RTAI_LOG_LEVEL`` is not a recognized logging level."""


def resolve_log_level(raw_value: str | None) -> str:
    """Validate and normalize the configured log level (uppercase).

    Unset/empty resolves to ``INFO``; anything else must be one of the
    standard levels or :class:`InvalidLogLevelError` is raised — there is
    no silent fallback.
    """
    value = (raw_value or "").strip().upper()
    if not value:
        return _DEFAULT_LEVEL
    if value not in _VALID_LEVELS:
        valid = ", ".join(_VALID_LEVELS)
        raise InvalidLogLevelError(
            f"Unknown {LOG_LEVEL_ENV_KEY} value {raw_value!r}; expected one of: {valid}"
        )
    return value


def short_id(value: str | None, length: int = 8) -> str:
    """Deterministic, safe correlation alias for an identifier.

    Full session/turn/request/message ids may embed user data, so only a
    stable prefix is ever emitted.
    """
    if not value:
        return ""
    return value[:length]


class EventFormatter(logging.Formatter):
    """Human-readable structured line: time level logger event key=value."""

    def __init__(self) -> None:
        super().__init__()
        self.converter = time.gmtime

    def format(self, record: logging.LogRecord) -> str:
        event = getattr(record, "event", None)
        meta = getattr(record, "meta", None)
        parts = [
            self.formatTime(record, "%Y-%m-%dT%H:%M:%SZ"),
            record.levelname,
            record.name,
        ]
        if event:
            parts.append(str(event))
        elif record.getMessage():
            parts.append(record.getMessage())
        if isinstance(meta, dict):
            for key in sorted(meta):
                parts.append(f"{key}={meta[key]}")
        return " ".join(parts)


def log_event(logger: logging.Logger, level: int, event: str, **meta: Any) -> None:
    """Emit one structured lifecycle record with a stable event name."""
    logger.log(level, "%s", event, extra={"event": event, "meta": meta})


def build_logging_config(
    level: str, *, filename: str | None = None
) -> dict[str, Any]:
    """Return a ``logging.config.dictConfig``-compatible configuration."""
    handlers: dict[str, Any] = {
        "stderr": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stderr",
            "formatter": "event",
        }
    }
    root_handlers = ["stderr"]
    if filename:
        handlers["file"] = {
            "class": "logging.FileHandler",
            "filename": filename,
            "encoding": "utf-8",
            "formatter": "event",
        }
        root_handlers.append("file")
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"event": {"()": EventFormatter}},
        "handlers": handlers,
        "root": {"level": level, "handlers": root_handlers},
        "loggers": {
            name: {"level": level, "handlers": [], "propagate": True}
            for name in _UVICORN_LOGGERS
        },
    }


def configure_logging(
    level: str | None = None,
    *,
    filename: str | None = None,
) -> str:
    """Apply the structured logging configuration.

    ``level`` defaults to ``RTAI_LOG_LEVEL`` (``INFO`` when unset).
    ``filename`` optionally adds a file handler (used by E2E fixtures to
    capture CI artifacts).  Returns the resolved level name.  Calling this
    again replaces the previous configuration (``dictConfig`` is
    idempotent, so handlers are never duplicated).
    """
    resolved = resolve_log_level(
        level if level is not None else os.environ.get(LOG_LEVEL_ENV_KEY)
    )
    logging.config.dictConfig(build_logging_config(resolved, filename=filename))
    return resolved


__all__ = [
    "EventFormatter",
    "InvalidLogLevelError",
    "LOG_LEVEL_ENV_KEY",
    "build_logging_config",
    "configure_logging",
    "log_event",
    "resolve_log_level",
    "short_id",
]
