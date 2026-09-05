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

import contextlib
import threading
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
    # Distinct idle-cleanup closure event emitted by the backend idle reaper the
    # moment it selects one or more sessions for closure. Carries only safe
    # metadata (reason + a bounded count) — never a session id (shortened or
    # otherwise), path, prompt, model, tool data, exception, or secret.
    "SESSION_IDLE_EXPIRED": "session.idle_expired",
    # Boolean-only identity evidence for every POST /assistant: what the client
    # actually sent (state/sessionId/threadId presence) and the resolver outcome
    # (isNew). Never carries the id value itself.
    "SESSION_IDENTITY": "session.identity",
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
    # Application-shell lifecycle (recorded by the app supervisor in main.py).
    "APP_STARTING": "app.starting",
    "APP_READY": "app.ready",
    "APP_SHUTTING_DOWN": "app.shutting_down",
    # Safe bounded counts after create/close transitions (recorded by the
    # session manager into the central hub): liveSessions, creatingSessions,
    # closingSessions, liveAdapters (ints only).
    "APP_COUNTS": "app.counts",
    # Session/adapter lifecycle owner points recorded by the session manager.
    "ADAPTER_CREATION_REQUESTED": "adapter.creation_requested",
    "ADAPTER_SPAWNED": "adapter.spawned",
    "ADAPTER_EXITED": "adapter.exited",
    # Safe observability: ACP tool-result and permission projection events.
    "TOOL_CONTENT_MAPPED":       "tool.content.mapped",
    "TOOL_RESULT_PROJECTED":     "tool.result.projected",
    "PERMISSION_PROJECTED":      "permission.projected",
    "CLIENT_TOOL_GROUP_VISIBILITY": "client.tool_group_visibility",
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


class DiagnosticsHub:
    """THE one global, bounded, safe diagnostics hub for the whole RTAI app.

    Every diagnostics event — app lifecycle, session/adapter lifecycle,
    prompt/tool/permission events, and validated client diagnostics — is
    recorded into this single ring buffer. Per-session recorders are facades
    (views) over this hub that tag events with a short session correlation id
    and read back only that session's events; they hold no event storage of
    their own, so the app never runs competing per-session and global logging
    systems.

    Safety is inherited from the module-level sanitizer: no prompts, model
    output, tool args/results, file paths, raw ACP payloads, process command
    lines, credentials, tokens, headers, or model/config identifiers are ever
    recorded. Field values are scalars only (short strings, booleans, bounded
    ints/floats). Each event also carries a stable, monotonic integer ``seq``
    (assigned here, the single owner point) so the Logs UI can dedupe when the
    same hub is observed through two views.
    """

    def __init__(self, max_events: int = MAX_EVENTS) -> None:
        self._max = max_events
        self._events: deque[dict[str, Any]] = deque(maxlen=max_events)
        self._seq = 0
        self._lock = threading.Lock()

    def record(self, event: str, level: str = "info", **fields: Any) -> int:
        """Record one event; returns its stable, monotonic hub sequence id."""
        # Defensive: an event name is a required, non-empty string. If a caller
        # ever passes null/None, record an honest unknown marker instead of
        # shipping a null "event" field to the UI.
        if not isinstance(event, str) or not event:
            event = "unknown"
        if level not in _LEVELS:
            level = "info"
        entry: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": event,
            "level": level,
        }
        entry.update(_sanitize(fields))
        # Client-recorded events pass origin:"client"; everything else is
        # honestly attributed to the server by default.
        entry.setdefault("origin", "server")
        with self._lock:
            self._seq += 1
            entry["seq"] = self._seq
            self._events.append(entry)
        return entry["seq"]

    def snapshot(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Return a copy of the retained events, oldest first (bounded)."""
        with self._lock:
            events = [dict(e) for e in self._events]
        if limit is not None:
            if limit <= 0:
                return []
            events = events[-int(limit):]
        return events


_hub: DiagnosticsHub | None = None


def get_diagnostics_hub() -> DiagnosticsHub:
    """Process-wide singleton hub shared by all recorders and the supervisor."""
    global _hub
    if _hub is None:
        _hub = DiagnosticsHub()
    return _hub


class SessionDiagnosticsRecorder(DiagnosticsRecorder):
    """Per-session VIEW of the one global hub — not a separate recorder.

    Duck-type compatible with ``DiagnosticsRecorder`` (record/snapshot/clear) so
    it can be linked to the adapter (``adapter.diag``), the transport dispatch,
    and the session entry exactly as before. Every record is written into the
    shared ``DiagnosticsHub`` tagged with the session's SHORT correlation id
    (a caller-passed ``session=`` short id wins), and ``snapshot()`` returns
    only this session's events from the hub — the active-session
    AssistantTransport projection is therefore a filtered view of the same hub.
    ``clear()`` is a deliberate no-op: session teardown must never erase global
    diagnostics history.
    """

    def __init__(self, session_short_id: str, hub: DiagnosticsHub | None = None) -> None:
        super().__init__()
        self._session = session_short_id
        # Bounded references (stable hub seq ids) to this recorder's own events —
        # an index into the ONE hub, never a second event store.
        self._seqs: deque[int] = deque(maxlen=MAX_EVENTS)
        self._hub = hub if hub is not None else get_diagnostics_hub()

    def record(self, event: str, level: str = "info", **fields: Any) -> None:
        # Deliberately does NOT inject a session/correlation id. The Logs page must
        # never render a shortened id of any kind (session, permission, tool, option,
        # or otherwise); only safe scalar fields reach the single hub. View
        # membership stays exact via the bounded ``_seqs`` index, not the id field.
        seq = self._hub.record(event, level, **fields)
        if seq is not None:
            self._seqs.append(seq)

    def snapshot(self) -> list[dict[str, Any]]:
        # Filter by this recorder's own bounded seq references rather than by the
        # ``session`` field: adapter-internal events legitimately carry a
        # different short ACP session id, while view membership must stay exact.
        wanted = set(self._seqs)
        return [e for e in self._hub.snapshot() if e.get("seq") in wanted]

    def clear(self) -> None:
        return None


class AppSupervisor:
    """Smallest explicit app-level supervisor, owned by the FastAPI lifespan.

    Owns the app lifecycle status and the one global diagnostics hub, and
    coordinates (never replaces) the existing session manager: the session
    manager remains the sole owner of ACP/OpenCode child processes and funnels
    its lifecycle events into the supervisor-owned hub. ``main.create_app``
    creates exactly one supervisor, calls ``record_starting`` /
    ``record_ready`` / ``record_shutting_down`` at the exact lifespan points,
    and exposes it via ``app.state.supervisor`` for the read-only
    ``GET /api/diagnostics`` endpoint.
    """

    _STATUS_TOKENS = ("starting", "ready", "shutting_down", "unknown")

    def __init__(
        self,
        hub: DiagnosticsHub | None = None,
        counts_provider: Any | None = None,
    ) -> None:
        super().__init__()
        self._hub = hub if hub is not None else get_diagnostics_hub()
        self._status = "starting"
        # Coordination hook owned by the lifespan: returns the session manager's
        # safe registry counts {live, creating, closing, liveAdapters} (ints only).
        self._counts_provider = counts_provider

    @property
    def status(self) -> str:
        return self._status

    def record_starting(self) -> None:
        self._status = "starting"
        with contextlib.suppress(Exception):
            self._hub.record(EVENT["APP_STARTING"], "info")

    def record_ready(self) -> None:
        self._status = "ready"
        with contextlib.suppress(Exception):
            self._hub.record(EVENT["APP_READY"], "info")

    def record_shutting_down(self) -> None:
        self._status = "shutting_down"
        with contextlib.suppress(Exception):
            self._hub.record(EVENT["APP_SHUTTING_DOWN"], "info")

    def snapshot_events(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Bounded recent events from the central hub (oldest first)."""
        return self._hub.snapshot(limit)

    def snapshot(self, event_limit: int | None = None) -> dict[str, Any]:
        """Bounded, safe, read-only snapshot for ``GET /api/diagnostics``.

        Returns the app lifecycle status, safe registry counts (via the counts
        provider injected by the lifespan), and the bounded recent event list
        from the central hub. Never includes prompts, text, responses, file
        paths, tool args/results, ACP payloads, process command lines,
        credentials, tokens, headers, or model/config identifiers or values.
        """
        counts: dict[str, int] = {}
        if self._counts_provider is not None:
            with contextlib.suppress(Exception):
                counts = self._counts_provider()
        return {
            "app": {"status": self._status},
            "counts": counts,
            "events": self._hub.snapshot(event_limit),
        }
