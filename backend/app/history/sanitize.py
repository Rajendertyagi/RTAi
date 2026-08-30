"""Sanitize Protocol v1 event payloads before persistence.

Only trusted conversation fields are kept. Tool content, ``raw_input``,
``locations``, raw diagnostics and unknown extension payloads are dropped by
default so that credentials, file contents, process commands and
provider-native payloads never reach the database. This preserves the
interleaved message/tool structure of a conversation while respecting privacy.
"""

from __future__ import annotations

from typing import Any

#: Trusted fields persisted per event type. Anything not listed is dropped.
_TRUSTED_FIELDS: dict[str, frozenset[str]] = {
    "user_message": frozenset(
        {
            "type",
            "session_id",
            "turn_id",
            "message_id",
            "text",
            "prompt",
        }
    ),
    "delta": frozenset({"type", "session_id", "turn_id", "message_id", "sequence", "text"}),
    "part_start": frozenset({"type", "session_id", "turn_id", "part_id", "part_type"}),
    "part_delta": frozenset({"type", "session_id", "turn_id", "part_id", "text"}),
    "part_done": frozenset({"type", "session_id", "turn_id", "part_id"}),
    "done": frozenset({"type", "session_id", "turn_id", "reason"}),
    "error": frozenset({"type", "session_id", "turn_id", "message", "code"}),
    "cancelled": frozenset({"type", "session_id", "turn_id"}),
    "tool_start": frozenset(
        {"type", "session_id", "turn_id", "tool_call_id", "title", "kind", "status"}
    ),
    "tool_update": frozenset({"type", "session_id", "turn_id", "tool_call_id", "status"}),
    "tool_result": frozenset({"type", "session_id", "turn_id", "tool_call_id", "status"}),
    "permission_request": frozenset(
        {"type", "session_id", "turn_id", "permission_request_id", "tool_call_id"}
    ),
    "permission_result": frozenset(
        {"type", "session_id", "turn_id", "permission_request_id", "option_id"}
    ),
}


def is_persistable(event_type: str) -> bool:
    """True when an event type is a trusted conversation event worth storing."""
    return event_type in _TRUSTED_FIELDS


def sanitize_event_payload(frame: dict[str, Any]) -> dict[str, Any]:
    """Return a sanitized copy of a normalized Protocol v1 frame.

    Returns an empty dict for event types that are not persisted.
    For ``user_message``, attachment metadata (``prompt``) is kept but raw
    content fields are stripped to prevent accidental persistence of bases,
    file bytes, or embedded text.
    """
    event_type = str(frame.get("type") or "")
    allowed = _TRUSTED_FIELDS.get(event_type)
    if allowed is None:
        return {}
    result: dict[str, Any] = {key: frame[key] for key in allowed if key in frame}
    # Redact raw content from prompt attachment metadata.
    if event_type == "user_message" and "prompt" in result:
        safe_prompt = []
        for block in result["prompt"]:
            if not isinstance(block, dict):
                continue
            safe_block: dict[str, Any] = {
                "kind": block.get("kind"),
                "name": block.get("name", ""),
            }
            if isinstance(block.get("mime_type"), str):
                safe_block["mime_type"] = block["mime_type"]
            if isinstance(block.get("size_bytes"), int):
                safe_block["size_bytes"] = block["size_bytes"]
            safe_prompt.append(safe_block)
        result["prompt"] = safe_prompt
    return result


def build_event_key(
    event_type: str,
    turn_id: str | None,
    message_id: str | None,
    sequence: int | None,
) -> str:
    """Deterministic, non-null idempotency key for one event.

    Timestamp is deliberately excluded: a retry may carry a different
    timestamp but must still deduplicate against the original.
    """
    return "|".join(
        [
            event_type,
            turn_id or "",
            message_id or "",
            str(sequence) if sequence is not None else "",
        ]
    )
