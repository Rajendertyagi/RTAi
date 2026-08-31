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
    AttachmentCapabilities,
    CapabilitySection,
    CapabilitySnapshot,
    CommandDescriptor,
    UnavailabilityReason,
    UnavailableCapability,
)

PROTOCOL_VERSION = 1

#: Known command types and their required payload fields (beyond the envelope).
_COMMAND_REQUIRED: dict[str, frozenset[str]] = {
    "prompt": frozenset({"session_id", "turn_id", "message_id"}),
    "cancel": frozenset({"session_id", "turn_id"}),
    "select_agent": frozenset({"session_id", "agent_id"}),
    "select_model": frozenset({"session_id", "model_id"}),
    "select_mode": frozenset({"session_id", "mode_id"}),
    "set_thinking": frozenset({"session_id", "level"}),
    "permission_response": frozenset(
        {"session_id", "turn_id", "permission_request_id", "option_id"}
    ),
}

# Valid attachment block kinds and their required fields (beyond the envelope).
_ATTACHMENT_KINDS = frozenset(
    {
        "text",
        "image",
        "audio",
        "resource_link",
        "embedded_text",
        "embedded_blob",
    }
)

_ATTACHMENT_REQUIRED_FIELDS: dict[str, frozenset[str]] = {
    "text": frozenset({"kind", "name", "text"}),
    "image": frozenset({"kind", "name", "data_base64", "mime_type"}),
    "audio": frozenset({"kind", "name", "data_base64", "mime_type"}),
    "resource_link": frozenset({"kind", "name", "uri"}),
    "embedded_text": frozenset({"kind", "name", "text", "mime_type"}),
    "embedded_blob": frozenset({"kind", "name", "data_base64", "mime_type"}),
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

    # Prompt-specific validation: text and prompt are mutually exclusive;
    # at least one must be present.
    if kind == "prompt":
        has_text = "text" in payload
        has_prompt = "prompt" in payload
        if not has_text and not has_prompt:
            return False, "missing_fields: text or prompt"
        if has_text and has_prompt:
            return False, "mutually_exclusive: text and prompt"
        if has_prompt:
            ok, err = _validate_prompt_blocks(payload["prompt"])
            if not ok:
                return False, err

    return True, None


def _validate_prompt_blocks(blocks: list[Any]) -> tuple[bool, str | None]:
    """Validate the optional ordered prompt block collection."""
    if not isinstance(blocks, list):
        return False, "prompt must be an array"
    if not blocks:
        return False, "prompt must contain at least one block"
    for i, block in enumerate(blocks):
        if not isinstance(block, dict):
            return False, f"prompt[{i}] must be an object"
        kind = block.get("kind")
        if kind not in _ATTACHMENT_KINDS:
            return False, f"prompt[{i}]: unknown kind {kind!r}"
        required = _ATTACHMENT_REQUIRED_FIELDS[kind]
        missing = required - set(block.keys())
        if missing:
            return False, f"prompt[{i}]: missing {sorted(missing)}"
        # Mutually exclusive fields per kind.
        has_text = "text" in block
        has_b64 = "data_base64" in block
        has_uri = "uri" in block
        if kind == "text" and (has_b64 or has_uri):
            return False, f"prompt[{i}]: text kind must not have data_base64 or uri"
        if kind in ("image", "audio", "embedded_blob") and (has_text or has_uri):
            return False, f"prompt[{i}]: {kind} kind must not have text or uri"
        if kind in ("resource_link", "embedded_text") and (has_b64 or has_text):
            return False, f"prompt[{i}]: {kind} kind must not have data_base64 or text"
    return True, None


def normalize_emission(
    raw: dict[str, Any],
    *,
    session_id: str,
    turn_id: str | None,
    sequence: int,
    message_id: str | None = None,
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
    # Inject message_id for part events so the frontend can correlate
    # reasoning/text parts to the assistant message they belong to.
    if message_id is not None:
        frame["message_id"] = message_id
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
    # attachments_available
    events.append(_attachments_event(snapshot.attachments))

    return events


def _section_event(event_type: str, section: CapabilitySection[Any]) -> dict[str, Any]:
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


def _attachments_event(
    attachments: Any,
) -> dict[str, Any]:
    """Map AttachmentCapabilities into a Protocol v1 attachments_available event."""
    if isinstance(attachments, AttachmentCapabilities):
        return {
            "type": "attachments_available",
            "available": True,
            "block_types": list(attachments.block_types),
            "max_item_bytes": attachments.max_item_bytes,
            "max_total_bytes": attachments.max_total_bytes,
            "max_count": attachments.max_count,
        }
    # Unavailable — reason-code event.
    if isinstance(attachments, UnavailableCapability):
        return {
            "type": "attachments_available",
            "available": False,
            "reason_code": attachments.reason.value,
            "reason_message": attachments.message,
        }
    # Fallback (PENDING_DISCOVERY before init): report unavailable.
    return {
        "type": "attachments_available",
        "available": False,
        "reason_code": UnavailabilityReason.PENDING_DISCOVERY.value,
        "reason_message": "Attachment capabilities are not yet available.",
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

    def register(self, permission_request_id: str, future: asyncio.Future[Any]) -> None:
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
