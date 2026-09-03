"""Permanent, production-safe diagnostics for one RTAI assistant session.

This is intentionally NOT temporary debug logging. Every event is safe by
construction: no prompt text, model output, tool args/results, files, paths,
credentials, tokens, raw ACP payloads, or full identifiers are ever recorded.
Identifiers are pre-shortened by call sites (``logging_config.short_id``); the
recorder additionally refuses sensitive field names and truncates any string.

A single shared event-name vocabulary (``EVENT``) is used everywhere so the
backend and the Web UI stay in sync. No ad hoc strings are scattered through the
codebase.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Any, Mapping

# Hard cap on retained events per session (bounded ring buffer).
MAX_EVENTS = 200

# Shared event-name vocabulary. Always reference these constants.
EVENT = {
    "ASSISTANT_REQUEST_RECEIVED": "assistant.request.received",
    "SESSION_RESOLVED": "session.resolved",
    "CAPABILITY_REFRESH_REQUESTED": "capability.refresh.requested",
    "CAPABILITY_SELECTION_REQUESTED": "capability.selection.requested",
    "ACP_CONFIG_OPTION_SENT": "acp.config_option.sent",
    "ACP_CONFIG_OPTION_CONFIRMED": "acp.config_option.confirmed",
    "ACP_CONFIG_OPTION_FAILED": "acp.config_option.failed",
    "PROMPT_STARTED": "prompt.started",
    "PROMPT_COMPLETED": "prompt.completed",
    "PROMPT_FAILED": "prompt.failed",
    "TOOL_START": "tool.start",
    "TOOL_UPDATE": "tool.update",
    "TOOL_RESULT": "tool.result",
    "PERMISSION_RECEIVED": "permission.received",
    "PERMISSION_ATTACHED": "permission.attached",
    "PERMISSION_RESPONDED": "permission.responded",
    "PERMISSION_RESOLVED": "permission.resolved",
    "PERMISSION_EXPIRED": "permission.expired",
    "PERMISSION_PROTOCOL_ERROR": "permission.protocol_error",
    "STATE_PROJECTED": "state.projected",
    "STATE_FLUSHED": "state.flushed",
    "STREAM_COMPLETED": "stream.completed",
    "STREAM_FAILED": "stream.failed",
    "SESSION_CLOSED": "session.closed",
    "SESSION_REUSED": "session.reused",
    "SESSION_CREATED": "session.created",
    "SESSION_CLOSING": "session.closing",
    "TRANSPORT_READY": "transport.ready",
    "TRANSPORT_UNAVAILABLE": "transport.unavailable",
    "ADAPTER_READY": "adapter.ready",
    "ADAPTER_UNAVAILABLE": "adapter.unavailable",
    "CAPABILITY_SNAPSHOT_RECEIVED": "capability.snapshot.received",
    "CAPABILITY_REFRESH_FAILED": "capability.refresh.failed",
    "CAPABILITY_SELECTION_UNAVAILABLE": "capability.selection.unavailable",
    "MODEL_REASSERTED": "model.reasserted",
    "MODEL_OPTION_DISCOVERED": "model.option.discovered",
    "ACP_CONFIG_OPTION_ECHO": "acp.config_option.echo",
    "MODEL_ECHO_MATCH": "model.echo.match",
    "MODEL_ECHO_MISMATCH": "model.echo.mismatch",
    "MODEL_CONFIRMED": "model.confirmed",
    "CAPABILITY_ECHO_MATCH": "capability.echo.match",
    "CAPABILITY_ECHO_MISMATCH": "capability.echo.mismatch",
    "CAPABILITY_SELECTION_UNCONFIRMED": "capability.selection.unconfirmed",
    "PROMPT_COMMAND_RECEIVED": "prompt.command.received",
    "PROMPT_CANCELLED": "prompt.cancelled",
    "PART_START": "part.start",
    "PART_DELTA": "part.delta",
    "PART_DONE": "part.done",
    "FIRST_STREAM_EVENT": "stream.first_event",
    "PERMISSION_CORRELATED": "permission.correlated",
    "PERMISSION_REDELIVERED": "permission.redelivered",
    "STATE_PROJECTION_FAILED": "state.projection.failed",
    "STATE_FLUSH_FAILED": "state.flush.failed",
    "TRANSPORT_COMMAND_RECEIVED": "transport.command.received",
    "PERMISSION_RESPONSE_RECEIVED": "permission.response.received",
    "TRANSPORT_COMMAND_ERROR": "transport.command.error",
    "CLIENT_GATE_READY": "client.gate_ready",
    "CLIENT_CAPABILITY_COMMAND_SENT": "client.capability_command_sent",
    "CLIENT_MODEL_COMMAND_SENT": "client.model_command_sent",
    "CLIENT_PERMISSION_POST_INITIATED": "client.permission_post_initiated",
    "CLIENT_ERROR": "client.error",
}

# Field names that must never reach diagnostics even by mistake.
_SENSITIVE_KEYS = frozenset(
    {
        "text",
        "prompt",
        "output",
        "content",
        "args",
        "argsText",
        "result",
        "raw_input",
        "rawInput",
        "tool_call",
        "toolCall",
        "toolCallId",
        "tool_call_id",
        "file",
        "path",
        "token",
        "api_key",
        "apikey",
        "password",
        "secret",
        "credential",
        "authorization",
        "cookie",
        "payload",
        "data",
    }
)

_LEVELS = frozenset({"debug", "info", "warn", "error"})


def _safe_value(value: Any, depth: int = 0) -> Any:
    """Return a safe scalar representation, or drop the value entirely."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        cleaned = value.replace("\n", " ").replace("\r", " ").strip()
        if len(cleaned) > 64:
            cleaned = cleaned[:64]
        return cleaned or None
    if depth > 0:
        # Never recurse into nested structures; collapse to a safe token.
        return f"<{type(value).__name__}>"
    return None


def _sanitize(fields: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in fields.items():
        if key in _SENSITIVE_KEYS:
            continue
        safe = _safe_value(value)
        if safe is None and not isinstance(value, (bool, int, float)):
            continue
        out[key] = safe
    return out


class DiagnosticsRecorder:
    """Bounded ring buffer of safe diagnostic events for one session."""

    def __init__(self, max_events: int = MAX_EVENTS) -> None:
        self._max = max_events
        self._events: deque[dict[str, Any]] = deque(maxlen=max_events)

    def record(self, event: str, level: str = "info", **fields: Any) -> None:
        if level not in _LEVELS:
            level = "info"
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": event,
            "level": level,
        }
        entry.update(_sanitize(fields))
        self._events.append(entry)

    def snapshot(self) -> list[dict[str, Any]]:
        """Return a copy of the retained events, oldest first."""
        return [dict(e) for e in self._events]

    def clear(self) -> None:
        self._events.clear()
