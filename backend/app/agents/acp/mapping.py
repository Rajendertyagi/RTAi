"""Pure ACP -> Protocol v1 translation helpers.

Everything here is a function of its arguments: no I/O, no adapter state, no
logging. That keeps the shared core testable and lets any ACP-backed adapter
reuse the same mapping without inheriting anything else.

The shapes come from the ACP specification, not from any one agent, so a
second ACP agent gets identical behaviour for free.
"""

from __future__ import annotations

from typing import Any

from ...core.protocol import jsonable_model

# ACP ToolCallStatus -> Protocol v1 ToolStatus.
#
# Note the vocabulary deliberately differs: ACP says "completed"/"failed",
# RTAI says "success"/"error". Translating here means the rest of the backend
# and the whole frontend only ever see the RTAI vocabulary.
TOOL_STATUS_MAP = {
    "pending": "pending",
    "in_progress": "running",
    "completed": "success",
    "failed": "error",
}

# ACP terminal statuses that close a tool call with tool_result.
TERMINAL_STATUSES = frozenset({"success", "error"})


def map_tool_status(status: Any) -> str | None:
    """Map an ACP tool-call status to a Protocol v1 ToolStatus.

    Unknown values pass through unchanged so a new ACP status stays visible in
    the UI rather than silently becoming "running".
    """
    if not isinstance(status, str):
        return None
    return TOOL_STATUS_MAP.get(status, status)


def map_tool_content(content: Any) -> list[dict[str, Any]] | None:
    """Map ACP tool-call content blocks to a typed Protocol v1 shape.

    ACP content is a discriminated union of ``content`` (text), ``diff``
    (file edit) and ``terminal`` (terminal reference) blocks. Only these known
    types are forwarded, each with an allow-listed field set, so arbitrary
    agent payloads cannot reach the UI unchecked.
    """
    if not isinstance(content, list):
        return None
    blocks: list[dict[str, Any]] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "content":
            item: dict[str, Any] = {"type": "content"}
            text = block.get("text")
            if isinstance(text, str):
                item["text"] = text
            blocks.append(item)
        elif block_type == "diff":
            item = {"type": "diff", "path": str(block.get("path", ""))}
            old_text = block.get("oldText")
            new_text = block.get("newText")
            if isinstance(old_text, str):
                item["oldText"] = old_text
            if isinstance(new_text, str):
                item["newText"] = new_text
            blocks.append(item)
        elif block_type == "terminal":
            blocks.append(
                {"type": "terminal", "terminalId": str(block.get("terminalId", ""))}
            )
    return blocks or None


def map_tool_locations(locations: Any) -> list[dict[str, Any]] | None:
    """Map ACP ToolCallLocation entries to ``{path, line?}`` items."""
    if not isinstance(locations, list):
        return None
    items: list[dict[str, Any]] = []
    for loc in locations:
        if not isinstance(loc, dict):
            continue
        path = loc.get("path")
        if not isinstance(path, str):
            continue
        item: dict[str, Any] = {"path": path}
        line = loc.get("line")
        if isinstance(line, int) and not isinstance(line, bool):
            item["line"] = line
        items.append(item)
    return items or None


def permission_option(option: Any) -> dict[str, str] | None:
    """Map one ACP ``PermissionOption`` to a Protocol v1 item.

    This function is the single ACP wire boundary for permission options. The
    official ACP v1 shape is ``optionId``/``name``/``kind``; the pinned SDK
    models it as pydantic field ``option_id`` with alias ``optionId`` and has
    no ``id`` field at all. Both accepted inputs carry the official
    identifier under its official name:

    - a pydantic ``PermissionOption`` model -> typed attribute ``option_id``;
    - an alias-serialized dict (``jsonable_model``/raw wire) -> ``optionId``.

    No invented alias (``id``, ``label``, positional or label-derived ids) is
    accepted. An option without an official identifier returns ``None`` and
    the caller skips it; the identifier itself is preserved byte-for-byte.
    ``kind`` is included when present so the UI can auto-pick allow options.
    """
    if isinstance(option, dict):
        option_id = option.get("optionId")
        label = option.get("name")
        kind = option.get("kind")
    else:
        option_id = getattr(option, "option_id", None)
        label = getattr(option, "name", None)
        kind = getattr(option, "kind", None)
    if not isinstance(option_id, str) or not option_id:
        return None
    # Display label falls back to the exact identifier only for rendering;
    # the identifier itself is never derived from the label.
    item: dict[str, str] = {"id": option_id, "label": str(label) if label else option_id}
    if kind:
        item["kind"] = str(kind)
    return item


def permission_tool_details(tool_call: Any) -> dict[str, Any]:
    """Extract additive tool details for a permission_request event.

    The ACP SDK hands ``request_permission`` the full ToolCallUpdate model;
    forwarding its title/kind/rawInput/content/locations lets the permission
    card show exactly what is being approved. All fields are optional.
    """
    details: dict[str, Any] = {}
    dumped = jsonable_model(tool_call)
    if not isinstance(dumped, dict):
        return details
    title = dumped.get("title")
    if isinstance(title, str) and title:
        details["title"] = title
    kind = dumped.get("kind")
    if isinstance(kind, str) and kind:
        details["kind"] = kind
    if "rawInput" in dumped:
        details["raw_input"] = dumped.get("rawInput")
    content = map_tool_content(dumped.get("content"))
    if content:
        details["content"] = content
    locations = map_tool_locations(dumped.get("locations"))
    if locations:
        details["locations"] = locations
    return details


def tool_call_id_of(tool_call: Any, fallback: str) -> str:
    """Best-effort tool call id from a pydantic model or a dumped dict."""
    if isinstance(tool_call, dict):
        value = tool_call.get("toolCallId") or tool_call.get("tool_call_id")
    else:
        value = getattr(tool_call, "tool_call_id", None)
    if isinstance(value, str) and value:
        return value
    return fallback


__all__ = [
    "TERMINAL_STATUSES",
    "TOOL_STATUS_MAP",
    "map_tool_content",
    "map_tool_locations",
    "map_tool_status",
    "permission_option",
    "permission_tool_details",
    "tool_call_id_of",
]
