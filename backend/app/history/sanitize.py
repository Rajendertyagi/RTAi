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
    "part_start": frozenset(
        {"type", "session_id", "turn_id", "message_id", "part_id", "part_type"}
    ),
    "part_delta": frozenset({"type", "session_id", "turn_id", "message_id", "part_id", "text"}),
    "part_done": frozenset({"type", "session_id", "turn_id", "message_id", "part_id"}),
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


def event_discriminator(event_type: str, frame: dict[str, Any]) -> str | None:
    """Return the stable field that disambiguates one event of this family.

    Several event families can legitimately repeat within a single turn (or
    within one part/tool), and their distinguishing id is not part of the
    ``turn_id``/``message_id``/``sequence`` identity. This returns that field
    so the persisted ``event_key`` stays unique without collapsing separate
    events. Returns ``None`` when the family carries no such field.
    """
    if event_type in ("tool_start", "tool_update", "tool_result"):
        return frame.get("tool_call_id")
    if event_type in ("permission_request", "permission_result"):
        return frame.get("permission_request_id")
    if event_type in ("part_start", "part_delta", "part_done"):
        return frame.get("part_id")
    return None


def build_event_key(
    event_type: str,
    turn_id: str | None,
    message_id: str | None,
    sequence: int | None,
    discriminator: str | None = None,
) -> str:
    """Deterministic, non-null idempotency key for one event.

    Timestamp is deliberately excluded: a retry may carry a different
    timestamp but must still deduplicate against the original.

    ``sequence`` is the protocol per-turn sequence where one exists (``delta``)
    or a session-local occurrence value for families that repeat without a
    wire sequence (``part_delta``, ``tool_update``). ``discriminator`` is the
    stable per-family id (``tool_call_id``, ``permission_request_id``,
    ``part_id``) so separate events never collapse.
    """
    return "|".join(
        [
            event_type,
            turn_id or "",
            message_id or "",
            str(sequence) if sequence is not None else "",
            discriminator or "",
        ]
    )
