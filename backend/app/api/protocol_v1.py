"""Protocol v1 normalization and command dispatch.

Adapters emit raw event dicts (e.g. ``{"type": "delta", "text": "hi"}``).
This module:

1. Validates incoming UI→backend commands against the Protocol v1 contract.
2. Wraps adapter emissions into Protocol v1 frames with the correct envelope.
3. Maps ``CapabilitySnapshot`` sections into ``*_available`` events.
4. Tracks per-connection pending permission requests.

All envelope fields (``protocol_version``, ``session_id``, ``turn_id``,
``sequence``, ``timestamp``) are owned by this module — adapter emissions
must never overwrite them.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from ..agents.capabilities import (
    AgentDescriptor,
    CapabilitySection,
    CapabilitySnapshot,
    CommandDescriptor,
)

PROTOCOL_VERSION = 1

#: Known command types and their required payload fields (beyond the envelope).
_COMMAND_REQUIRED: dict[str, frozenset[str]] = {
    "prompt": frozenset({"session_id", "turn_id", "message_id", "text"}),
    "cancel": frozenset({"session_id", "turn_id"}),
    "select_agent": frozenset({"session_id", "agent_id"}),
    "select_model": frozenset({"session_id", "model_id"}),
    "select_mode": frozenset({"session_id", "mode_id"}),
    "set_thinking": frozenset({"session_id", "level"}),
    "permission_response": frozenset(
        {"session_id", "turn_id", "permission_request_id", "option_id"}
    ),
}


def validate_command(payload: dict[str, Any]) -> tuple[bool, str | None]:
    """Return (is_valid, error_message)."""
    if payload.get("protocol_version") != PROTOCOL_VERSION:
        return False, "unsupported_protocol_version"
    kind = payload.get("type")
    if kind not in _COMMAND_REQUIRED:
        return False, "unknown_command"
    required = _COMMAND_REQUIRED[kind]
    missing = required - set(payload.keys())
    if missing:
        return False, f"missing_fields: {sorted(missing)}"
    return True, None


def normalize_emission(
    raw: dict[str, Any],
    *,
    session_id: str,
    turn_id: str | None,
    sequence: int,
) -> dict[str, Any]:
    """Wrap an adapter emission with the Protocol v1 envelope.

    Envelope fields are authoritative and cannot be overwritten by the adapter.
    """
    frame: dict[str, Any] = {
        "protocol_version": PROTOCOL_VERSION,
        "session_id": session_id,
        "timestamp": int(time.time() * 1000),
    }
    if turn_id is not None:
        frame["turn_id"] = turn_id
    # Merge adapter-provided fields — protected envelope fields win.
    protected = {"protocol_version", "session_id", "turn_id"}
    for key, value in raw.items():
        if key not in protected:
            frame[key] = value
    # Inject sequence for delta events if absent.
    if frame.get("type") == "delta" and "sequence" not in frame:
        frame["sequence"] = sequence
    return frame


def snapshot_to_v1_events(snapshot: CapabilitySnapshot) -> list[dict[str, Any]]:
    """Map a CapabilitySnapshot into a list of Protocol v1 events."""
    events: list[dict[str, Any]] = []

    # agent_info — only when identity is available
    if isinstance(snapshot.agent, AgentDescriptor):
        events.append({"type": "agent_info", "name": snapshot.agent.label})

    # agents_available
    events.append(_section_event("agents_available", snapshot.agents))
    # models_available
    events.append(_section_event("models_available", snapshot.models))
    # modes_available
    events.append(_section_event("modes_available", snapshot.modes))
    # thinking_available
    events.append(_thinking_event(snapshot.thinking_options))
    # commands_available
    events.append(_section_event("commands_available", snapshot.commands))

    return events


def _section_event(
    event_type: str, section: CapabilitySection[Any]
) -> dict[str, Any]:
    """Map a CapabilitySection into a Protocol v1 available/ unavailable event."""
    # Explicit mapping avoids the fragile replace()+pluralize heuristic.
    _KEYS: dict[str, str] = {
        "agents_available": "agents",
        "models_available": "models",
        "modes_available": "modes",
        "commands_available": "commands",
    }
    key = _KEYS.get(event_type, event_type.replace("_available", "") + "s")
    if section.available:
        return {
            "type": event_type,
            "available": True,
            key: [_item_dict(item) for item in section.items],
        }
    assert section.unavailable is not None
    return {
        "type": event_type,
        "available": False,
        "reason_code": section.unavailable.reason.value,
        "reason_message": section.unavailable.message,
    }


def _item_dict(item: Any) -> dict[str, str]:
    """Convert a capability item to a plain dict."""
    if isinstance(item, AgentDescriptor):
        return {"id": item.id, "label": item.label}
    if isinstance(item, CommandDescriptor):
        d: dict[str, str] = {"id": item.name, "label": item.name}
        if item.description:
            d["description"] = item.description
        if item.input_hint:
            d["input_hint"] = item.input_hint
        return d
    if hasattr(item, "id") and hasattr(item, "label"):
        return {"id": item.id, "label": item.label}
    if isinstance(item, dict):
        return {"id": str(item.get("id", "")), "label": str(item.get("label", ""))}
    return {"id": str(item), "label": str(item)}


def _thinking_event(
    section: CapabilitySection[Any],
) -> dict[str, Any]:
    if section.available and section.items:
        return {
            "type": "thinking_available",
            "available": True,
            "thinking_levels": [str(t.id) for t in section.items],
        }
    if section.available:
        return {
            "type": "thinking_available",
            "available": True,
            "thinking_levels": [],
        }
    assert section.unavailable is not None
    return {
        "type": "thinking_available",
        "available": False,
        "reason_code": section.unavailable.reason.value,
        "reason_message": section.unavailable.message,
    }


class PermissionTracker:
    """Track pending permission requests per connection.

    Each entry maps ``permission_request_id`` → ``asyncio.Future``.
    Resolving or cancelling a future forwards the answer back to the adapter.
    """

    def __init__(self, timeout_seconds: float = 300.0) -> None:
        self._pending: dict[str, asyncio.Future[Any]] = {}
        self._timeout = timeout_seconds

    def register(
        self, permission_request_id: str, future: asyncio.Future[Any]
    ) -> None:
        self._pending[permission_request_id] = future

    def resolve(self, permission_request_id: str, option_id: str) -> bool:
        future = self._pending.pop(permission_request_id, None)
        if future is None or future.done():
            return False
        if not future.cancelled():
            future.set_result(option_id)
        return True

    def reject_unknown(self, permission_request_id: str) -> bool:
        """Cancel a future for an unknown request ID."""
        future = self._pending.pop(permission_request_id, None)
        if future is not None and not future.done():
            future.cancel()
        return future is not None

    def cancel_all(self) -> None:
        """Cancel all pending futures (on disconnect/close)."""
        for future in self._pending.values():
            if not future.done():
                future.cancel()
        self._pending.clear()

    @property
    def has_pending(self) -> bool:
        return bool(self._pending)
