"""Bridge the existing ACP adapter output into ``RunController.state``.

This module is the only place that translates the current ACP emission
contract (``part_start`` / ``part_delta`` / ``part_done`` / ``done`` /
``error`` / ``raw`` / ``tool_*``) into Assistant UI state operations.
It does not import ``protocol_v1`` or any frontend ``ServerEvent`` types and it
does not store status inside tool-call parts (tools are out of scope in Phase 1).

Phase 1 scope extended to tool-call streaming (Phase 2.5):
- user text ingestion already handled by the caller;
- one assistant message placeholder;
- streamed assistant text;
- streamed reasoning if the adapter supplies it;
- tool-call parts with official fields only;
- terminal completion / error / cancellation status.
"""

from __future__ import annotations

import contextlib
import json
import logging
import uuid
from typing import Any

from assistant_stream import RunController

from ...agents.capabilities import AgentDescriptor
from ...logging_config import log_event, short_id

logger = logging.getLogger(__name__)


def _ensure_assistant_message(controller: RunController) -> int:
    """Ensure a trailing assistant message exists; return its index."""
    state = controller.state
    if state is None:
        controller.state = {"messages": [], "status": "running"}
        state = controller.state
    try:
        messages = state["messages"]  # type: ignore[index]
    except KeyError:
        state["messages"] = []  # type: ignore[index]
        messages = state["messages"]
    try:
        length = len(messages)  # type: ignore[arg-type]
    except Exception:
        length = 0
    if length == 0:
        messages.append(
            {"role": "assistant", "id": str(uuid.uuid4()), "parts": [{"type": "text", "text": ""}]}
        )  # type: ignore[attr-defined]
        return 0
    try:
        last_role = messages[length - 1]["role"]  # type: ignore[index]
    except Exception:
        last_role = None
    if last_role != "assistant":
        messages.append(
            {"role": "assistant", "id": str(uuid.uuid4()), "parts": [{"type": "text", "text": ""}]}
        )  # type: ignore[attr-defined]
        return length
    try:
        last_parts = messages[length - 1]["parts"]  # type: ignore[index]
        if len(last_parts) == 0:  # type: ignore[arg-type]
            messages[length - 1]["parts"].append({"type": "text", "text": ""})  # type: ignore[attr-defined]
    except Exception:
        pass
    return length - 1


def _append_text_to_assistant(controller: RunController, delta: str, *, kind: str) -> None:
    """Stream a text or reasoning delta into the assistant message."""
    if not delta:
        return
    idx = _ensure_assistant_message(controller)
    state = controller.state
    if state is None:
        return
    messages = state["messages"]  # type: ignore[index]
    if kind == "reasoning":
        try:
            parts = messages[idx]["parts"]  # type: ignore[index]
            found = None
            for i in range(len(parts)):  # type: ignore[arg-type]
                try:
                    if parts[i]["type"] == "reasoning":  # type: ignore[index]
                        found = i
                        break
                except Exception:
                    continue
            if found is None:
                parts.append({"type": "reasoning", "text": ""})  # type: ignore[attr-defined]
                found = len(parts) - 1  # type: ignore[arg-type]
            parts[found]["text"] += delta  # type: ignore[index]
        except Exception:
            with contextlib.suppress(Exception):
                controller.append_state_text(["messages", idx, "parts", 1, "text"], delta)
    else:
        try:
            parts = messages[idx]["parts"]  # type: ignore[index]
            target = 0
            for i in range(len(parts)):  # type: ignore[arg-type]
                try:
                    if parts[i]["type"] == "text":  # type: ignore[index]
                        target = i
                        break
                except Exception:
                    continue
            parts[target]["text"] += delta  # type: ignore[index]
        except Exception:
            with contextlib.suppress(Exception):
                controller.append_state_text(["messages", idx, "parts", 0, "text"], delta)


def _set_status(controller: RunController, status: str, *, error: str | None = None) -> None:
    """Set the top-level turn status in state."""
    try:
        controller.state["status"] = status  # type: ignore[index]
        if error is not None:
            controller.state["error"] = error  # type: ignore[index]
        elif status not in {"error", "cancelled"}:
            try:
                cur = controller.state["error"]  # type: ignore[index]
                if isinstance(cur, str):
                    controller.state["error"] = ""  # type: ignore[index]
            except KeyError:
                pass
    except Exception:
        try:
            if controller.state is None:
                controller.state = {"messages": [], "status": status}  # type: ignore[assignment]
            else:
                controller.state["status"] = status  # type: ignore[index]
        except Exception:
            pass


def _find_tool_part_index(parts: Any, tool_call_id: str) -> int | None:
    try:
        n = len(parts)  # type: ignore[arg-type]
    except Exception:
        return None
    for i in range(n):  # type: ignore[arg-type]
        try:
            p = parts[i]  # type: ignore[index]
            if (
                isinstance(p, dict)
                and p.get("type") == "tool-call"
                and p.get("toolCallId") == tool_call_id
            ):
                return i
            # StateProxy case where p is a proxy but get still works via __getitem__
            if p.get("type") == "tool-call" and p.get("toolCallId") == tool_call_id:  # type: ignore[union-attr]
                return i
        except Exception:
            continue
    return None


# Block types emitted by the upstream mappers (map_tool_content /
# server_adapter._server_tool_content) that already have a safe, representable
# JSON shape. Anything else is dropped so unexpected credentials/metadata never
# reach the UI.
_REPRESENTABLE_TOOL_BLOCK_TYPES = frozenset(
    {"content", "text", "diff", "terminal", "image", "json", "data", "file"}
)
# Block types that are transport-only metadata and must never be forwarded.
_TRANSPORT_ONLY_TOOL_BLOCK_TYPES = frozenset({"metadata", "transport", "internal"})

# Sentinel returned by _derive_tool_result when there is genuinely no result
# content, so the caller can apply the honest terminal fallback string.
_NO_RESULT = object()


def _clean_tool_block(block: Any) -> Any:
    """Return a safe JSON-serializable view of a content block, or None to drop."""
    if not isinstance(block, dict):
        return block  # primitive list item, keep as-is
    block_type = block.get("type")
    if block_type in _TRANSPORT_ONLY_TOOL_BLOCK_TYPES:
        return None
    if block_type in _REPRESENTABLE_TOOL_BLOCK_TYPES:
        # Already an allow-listed shape produced by the upstream mappers.
        return block
    # Unknown type: keep only a plain text payload (best effort); otherwise drop
    # to avoid forwarding unexpected transport metadata.
    text = block.get("text")
    if isinstance(text, str) and text.strip():
        return {"type": "content", "text": text.strip()}
    return None


def _derive_tool_result(content: Any) -> Any:
    """Build a JSON-serializable result preserving all meaningful blocks.

    Returns ``_NO_RESULT`` when there is genuinely no result content, so the
    caller applies the honest terminal fallback. A single plain-text block
    collapses to a bare string (``ToolCallMessagePart.result`` accepts string);
    multiple or structured blocks are preserved as a list/object in original
    order. Transport-only metadata is excluded.
    """
    if content is None:
        return _NO_RESULT
    if isinstance(content, str):
        return content.strip() if content.strip() else _NO_RESULT
    if not isinstance(content, list):
        # Non-list structured value (dict/number/bool): preserve as-is.
        return content
    blocks: list[Any] = []
    for block in content:
        if not isinstance(block, dict):
            blocks.append(block)
            continue
        clean = _clean_tool_block(block)
        if clean is not None:
            blocks.append(clean)
    if not blocks:
        return _NO_RESULT
    if len(blocks) == 1:
        only = blocks[0]
        if (
            isinstance(only, dict)
            and only.get("type") in ("content", "text")
            and isinstance(only.get("text"), str)
        ):
            text = only["text"].strip()
            return text if text else _NO_RESULT
        # Single structured (non-text) block: preserve as object.
        return only
    return blocks


def _derive_tool_name(event: dict[str, Any]) -> str:
    # Prefer the closest real tool identifier from the event contract.
    # `kind`/`toolName`/`tool_name` are the agent-protocol tool identifiers;
    # `title` is a human display label and must NOT be claimed as the exact
    # tool name when a real identifier is available.
    for key in ("toolName", "tool_name", "kind", "title"):
        v = event.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    # Honest generic fallback (required by the official ToolCallMessagePart type).
    return "tool"


def _derive_tool_args(event: dict[str, Any]) -> tuple[dict[str, Any], str]:
    raw = event.get("raw_input")
    if raw is None:
        raw = event.get("rawInput")
    if raw is None:
        raw = event.get("args")
    if isinstance(raw, dict):
        # Preserve structured args when valid
        try:
            args_text = json.dumps(raw)
        except Exception:
            args_text = str(raw)
        return raw, args_text
    if isinstance(raw, str) and raw.strip():
        # Try to parse as JSON for args, keep original text as argsText
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed, raw
        except Exception:
            pass
        return {}, raw
    return {}, ""


# ACP permission option kinds use underscores (ACP wire format); Assistant UI
# approval option kinds use hyphens. The ONLY sanctioned translation at this
# single ACP -> Assistant UI boundary is the explicit four-way conversion below.
# No speculative aliases (allow/approve/accept, space-separated, or label-based)
# are accepted; unknown kinds stay unsupported and non-selectable.
_ACP_TO_AUI_APPROVAL_KIND = {
    "allow_once": "allow-once",
    "allow_always": "allow-always",
    "reject_once": "reject-once",
    "reject_always": "reject-always",
}

# Safe, user-facing copy for permission requests that carry no supported option.
_UNSUPPORTED_PERMISSION_REASON = "This permission type is not supported. Cancel this run."
# Safe, user-facing copy used when an ACP permission future is no longer active.
_EXPIRED_REASON = "Permission is no longer active."


def _map_approval_kind(kind: str | None) -> str | None:
    """Map an ACP permission option kind to an Assistant UI approval kind.

    Only the four documented ACP kinds are accepted. Unknown kinds return None
    and must NOT become selectable approval options. The exact ACP option id is
    preserved separately by the caller; only the kind vocabulary is translated.
    """
    if not isinstance(kind, str) or not kind:
        return None
    return _ACP_TO_AUI_APPROVAL_KIND.get(kind)


def _map_approval_option(option: dict[str, Any]) -> dict[str, Any] | None:
    """Map one supported ACP permission option to the official ToolApprovalOption.

    Returns None for options whose kind is unknown/unsupported so they are never
    exposed as selectable approval options or counted as valid registry entries.
    """
    # Options arrive already normalized at the single ACP wire boundary
    # (mapping.permission_option): the RTAI Protocol v1 identifier is ``id``,
    # carrying the official ACP ``optionId`` value byte-for-byte. No legacy
    # ``optionId``/``label`` aliases are accepted after that boundary.
    oid = option.get("id")
    if not isinstance(oid, str) or not oid:
        return None
    kind = _map_approval_kind(option.get("kind"))
    if kind is None:
        return None
    item: dict[str, Any] = {"id": oid, "kind": kind}
    label = option.get("label")
    if isinstance(label, str) and label:
        item["label"] = label
    description = option.get("description")
    if isinstance(description, str) and description:
        item["description"] = description
    return item


def _permission_meta_from_event(event: dict[str, Any]) -> dict[str, Any] | None:
    """Extract permission metadata from a permission_request protocol event.

    Only options with a supported (or proven-equivalent) kind are retained as
    selectable approval options and valid registry entries. Unknown kinds are
    collected as unsupported metadata only (never selectable). Returns None when
    required identifiers are missing so a malformed event never registers a
    dangling permission entry.
    """
    if not isinstance(event, dict):
        return None
    permission_id = event.get("permission_request_id")
    if not isinstance(permission_id, str) or not permission_id:
        return None
    tool_call_id = event.get("tool_call_id") or event.get("toolCallId")
    if not isinstance(tool_call_id, str) or not tool_call_id:
        return None
    raw_options = event.get("options")
    options: list[dict[str, Any]] = []
    unsupported_kinds: list[str] = []
    if isinstance(raw_options, list):
        for o in raw_options:
            if not isinstance(o, dict):
                continue
            mapped = _map_approval_option(o)
            if mapped is None:
                kind = o.get("kind")
                if isinstance(kind, str) and kind:
                    unsupported_kinds.append(kind)
                continue
            options.append(mapped)
    return {
        "permission_id": permission_id,
        "tool_call_id": tool_call_id,
        "options": options,
        "unsupported_kinds": unsupported_kinds,
    }


def project_capabilities(controller: RunController, snapshot: Any) -> None:
    """Project an authoritative CapabilitySnapshot into the namespaced capability section.

    Preserves exact adapter IDs and server-selected values, keeps display labels
    separate from IDs, and represents unsupported categories as ``None`` and an
    available-but-empty category as ``[]`` so the UI can disable or hide it. The
    single source of truth is the adapter's snapshot; nothing is mirrored under a
    second key and no defaults are substituted.
    """

    def items_of(section: Any) -> list[dict[str, str]] | None:
        if not getattr(section, "available", False):
            return None
        out: list[dict[str, str]] = []
        for d in section.items:
            out.append({"id": d.id, "label": d.label})
        return out

    raw_agent = getattr(snapshot, "agent", None)
    agent = (
        {"id": raw_agent.id, "label": raw_agent.label}
        if isinstance(raw_agent, AgentDescriptor)
        else None
    )

    selected = getattr(snapshot, "selected", None) or {}
    caps: dict[str, Any] = {
        "initialized": bool(selected)
        or any(
            getattr(s, "available", False)
            for s in (
                snapshot.agents,
                snapshot.models,
                snapshot.modes,
                snapshot.thinking_options,
            )
        ),
        "agent": agent,
        "agents": items_of(snapshot.agents),
        "models": items_of(snapshot.models),
        "modes": items_of(snapshot.modes),
        "thinkingOptions": items_of(snapshot.thinking_options),
        "selected": {
            "agent": selected.get("agent"),
            "model": selected.get("model"),
            "mode": selected.get("mode"),
            "thinking": selected.get("thinking"),
        },
        "error": None,
    }
    try:
        if controller.state is None:
            controller.state = {}
        controller.state["rtaiCapabilities"] = caps
        # --- DIAGNOSTIC (gated by RTAI_LOG_LEVEL=DEBUG): projection summary ---
        # Logs only booleans and section COUNTS (never option ids/values/labels).
        if logger.isEnabledFor(logging.DEBUG):
            _sel = caps.get("selected") or {}
            log_event(
                logger,
                logging.DEBUG,
                "assistant_capabilities_projected",
                initialized=bool(caps.get("initialized")),
                agent=bool(caps.get("agent")),
                agents=len(caps.get("agents") or []),
                models=len(caps.get("models") or []),
                modes=len(caps.get("modes") or []),
                thinking=len(caps.get("thinkingOptions") or []),
                selected_kinds=",".join(_sel.keys()),
            )
        controller.state["rtaiCapabilities"] = caps
    except Exception:
        pass


def set_capability_error(controller: RunController, kind: str, message: str) -> None:
    """Record a safe, payload-free transport error for a failed capability selection."""
    try:
        state = controller.state
        if state is None:
            return
        caps = state.get("rtaiCapabilities")
        if isinstance(caps, dict):
            caps["error"] = {"kind": kind, "message": message}
        else:
            state["rtaiCapabilities"] = {
                "initialized": True,
                "agent": None,
                "agents": None,
                "models": None,
                "modes": None,
                "thinkingOptions": None,
                "selected": {},
                "error": {"kind": kind, "message": message},
            }
    except Exception:
        pass


class AcpStateProjector:
    """Projects ACP adapter events into ``RunController.state``.

    Bound to a single turn's ``RunController`` and invoked via the stable
    ``AssistantTransportDispatch`` owned by the session entry.
    """

    def __init__(self, controller: RunController, *, session_key: str) -> None:
        self.controller = controller
        self.session_key = session_key
        self._part_kind_by_id: dict[str, str] = {}
        self._first_update_seen = False
        # Linked by AssistantTransportDispatch.bind; gives tool_result/done a way
        # to re-synchronize an approval the REST endpoint already resolved.
        self.permission_registry: Any | None = None

    def has_approval(self, permission_id: str) -> bool:
        """True if a tool part carries a pending (unresolved) approval with this id."""
        try:
            state = self.controller.state
            if state is None:
                return False
            messages = state["messages"]
            for message in messages:
                parts = message.get("parts") if isinstance(message, dict) else None
                if not isinstance(parts, list):
                    continue
                for part in parts:
                    if not isinstance(part, dict) or part.get("type") != "tool-call":
                        continue
                    approval = part.get("approval")
                    if not isinstance(approval, dict):
                        continue
                    if approval.get("id") != permission_id:
                        continue
                    return approval.get("approved") is None
            return False
        except Exception:
            return False

    def set_approval_expired(self, permission_id: str, reason: str) -> bool:
        """Mark the matching tool-call approval as expired (no approved/optionId).

        Returns False when the stream/session has already ended so the caller can
        still report the honest lifecycle state via the registry alone.
        """
        try:
            state = self.controller.state
            if state is None:
                return False
            messages = state["messages"]
            for message in messages:
                parts = message.get("parts") if isinstance(message, dict) else None
                if not isinstance(parts, list):
                    continue
                for part in parts:
                    if not isinstance(part, dict) or part.get("type") != "tool-call":
                        continue
                    approval = part.get("approval")
                    if not isinstance(approval, dict):
                        continue
                    if approval.get("id") != permission_id:
                        continue
                    approval["resolution"] = "expired"
                    approval["reason"] = reason
                    # Keep approved undefined; do NOT set an optionId.
                    return True
            return False
        except Exception:
            return False

    def _sync_registry_approval(self, tool_call_id: str, parts: list[Any], tool_idx: int) -> None:
        """Re-apply a permission resolution recorded in the session registry.

        Called on tool_result/done so an approval-state update that raced with a
        stream teardown is re-synchronized from the session registry (resolved
        optionId/approved OR an expired resolution). Only sets official approval
        fields; never invents a result.
        """
        registry = self.permission_registry
        if registry is None:
            return
        perm = registry.get_by_tool_call_id(tool_call_id)
        if perm is None or perm.resolution is None:
            return
        try:
            part = parts[tool_idx]
            if not isinstance(part, dict):
                return
            approval = part.get("approval")
            if not isinstance(approval, dict):
                approval = {"id": perm.permission_id}
                part["approval"] = approval
            if perm.resolution == "expired":
                approval["resolution"] = "expired"
                approval["reason"] = _EXPIRED_REASON
                return
            if (
                perm.resolution == "resolved"
                and perm.selected_option_id is not None
                and (approval.get("approved") is None or approval.get("optionId") is None)
            ):
                kind = perm.option_kinds.get(perm.selected_option_id, "")
                approval["optionId"] = perm.selected_option_id
                approval["approved"] = kind in ("allow-once", "allow-always")
        except Exception:
            return

    async def handle(self, event: dict[str, Any]) -> None:
        if not isinstance(event, dict):
            return
        etype = event.get("type")
        if not self._first_update_seen and etype in {
            "part_start",
            "part_delta",
            "raw",
            "tool_start",
        }:
            self._first_update_seen = True
            log_event(
                logger,
                logging.DEBUG,
                "assistant_first_acp_update",
                session=short_id(self.session_key),
                event_type=str(etype),
            )
        if etype == "part_start":
            part_id = event.get("part_id")
            part_type = event.get("part_type") or event.get("kind") or "text"
            if isinstance(part_id, str) and part_id:
                kind = "reasoning" if part_type == "reasoning" else "text"
                self._part_kind_by_id[part_id] = kind
                _ensure_assistant_message(self.controller)
            return
        if etype == "part_delta":
            part_id = event.get("part_id")
            text = event.get("text")
            if not isinstance(text, str) or not text:
                return
            kind = "text"
            if isinstance(part_id, str) and part_id in self._part_kind_by_id:
                kind = self._part_kind_by_id[part_id]
            else:
                pt = event.get("part_type")
                if pt == "reasoning":
                    kind = "reasoning"
            _append_text_to_assistant(self.controller, text, kind=kind)
            return
        if etype == "part_done":
            part_id = event.get("part_id")
            if isinstance(part_id, str):
                self._part_kind_by_id.pop(part_id, None)
            return
        if etype == "tool_start":
            # Map ACP tool_start into one official tool-call part
            tool_call_id = event.get("tool_call_id")
            if not isinstance(tool_call_id, str) or not tool_call_id:
                tool_call_id = event.get("toolCallId")
            if not isinstance(tool_call_id, str) or not tool_call_id:
                return
            tool_name = _derive_tool_name(event)
            args, args_text = _derive_tool_args(event)
            idx = _ensure_assistant_message(self.controller)
            try:
                state = self.controller.state
                if state is None:
                    return
                messages = state["messages"]  # type: ignore[index]
                parts = messages[idx]["parts"]  # type: ignore[index]
                # Append once to active assistant message; correlate later by toolCallId
                # Do not create duplicate if already exists (idempotent)
                if _find_tool_part_index(parts, tool_call_id) is None:
                    tool_part: dict[str, Any] = {
                        "type": "tool-call",
                        "toolCallId": tool_call_id,
                        "toolName": tool_name,
                        "args": args,
                        "argsText": args_text,
                    }
                    parts.append(tool_part)  # type: ignore[attr-defined]
            except Exception:
                pass
            return
        if etype == "tool_update":
            # Non-terminal pending/running updates: do not set result/status
            tool_call_id = event.get("tool_call_id")
            if not isinstance(tool_call_id, str) or not tool_call_id:
                tool_call_id = event.get("toolCallId")
            if not isinstance(tool_call_id, str) or not tool_call_id:
                return
            # Update official mutable fields only if meaningful
            # For tool_update, ACP may contain updated args or content; we handle args only
            raw = event.get("raw_input")
            if raw is None:
                raw = event.get("rawInput")
            if raw is None:
                # No meaningful supported data, keep existing part unchanged
                return
            # If raw_input present, update args/argsText
            args, args_text = _derive_tool_args(event)
            if not args and not args_text:
                return
            try:
                state = self.controller.state
                if state is None:
                    return
                messages = state["messages"]  # type: ignore[index]
                idx = _ensure_assistant_message(self.controller)
                parts = messages[idx]["parts"]  # type: ignore[index]
                tool_idx = _find_tool_part_index(parts, tool_call_id)
                if tool_idx is None:
                    return
                # Do not set result; only update args if changed
                part = parts[tool_idx]  # type: ignore[index]
                # Use proxy mutation to trigger update-state
                if args:
                    part["args"] = args  # type: ignore[index]
                if args_text:
                    part["argsText"] = args_text  # type: ignore[index]
            except Exception:
                pass
            return
        if etype == "tool_result":
            # Terminal: locate the existing part by toolCallId, then set a
            # defined result that preserves every meaningful content block.
            tool_call_id = event.get("tool_call_id")
            if not isinstance(tool_call_id, str) or not tool_call_id:
                tool_call_id = event.get("toolCallId")
            if not isinstance(tool_call_id, str) or not tool_call_id:
                return
            status = event.get("status")
            if not isinstance(status, str):
                status = str(status) if status is not None else "success"
            status_norm = status.lower() if isinstance(status, str) else "success"
            is_error = status_norm in {
                "error",
                "cancelled",
                "aborted",
                "timeout",
                "failure",
                "failed",
            }

            # Preserve ALL meaningful result blocks in original order. A single
            # plain-text block collapses to a string; multiple/structured blocks
            # are preserved as a JSON-serializable list/object. Genuinely empty
            # content falls back to the honest terminal placeholder below.
            result = _derive_tool_result(event.get("content"))
            if result is _NO_RESULT:
                em = event.get("error_message")
                if isinstance(em, str) and em.strip():
                    result = em.strip()
                else:
                    # Honest terminal fallback keeps result defined without
                    # inventing content. No credentials/metadata are logged.
                    result = f"Tool {status_norm}" if is_error else "<no result>"

            try:
                state = self.controller.state
                if state is None:
                    return
                messages = state["messages"]  # type: ignore[index]
                idx = _ensure_assistant_message(self.controller)
                parts = messages[idx]["parts"]  # type: ignore[index]
                tool_idx = _find_tool_part_index(parts, tool_call_id)
                if tool_idx is None:
                    # If tool_start was missed, create a minimal terminal part.
                    tool_name = _derive_tool_name(event)
                    args, args_text = _derive_tool_args(event)
                    tool_part: dict[str, Any] = {
                        "type": "tool-call",
                        "toolCallId": tool_call_id,
                        "toolName": tool_name,
                        "args": args,
                        "argsText": args_text,
                        "result": result,
                    }
                    if is_error:
                        tool_part["isError"] = True
                    parts.append(tool_part)  # type: ignore[attr-defined]
                else:
                    part = parts[tool_idx]  # type: ignore[index]
                    part["result"] = result  # type: ignore[index]
                    if is_error:
                        part["isError"] = True  # type: ignore[index]
                    else:
                        # Successful status must not be flagged as an error.
                        if part.get("isError"):  # type: ignore[union-attr]
                            part["isError"] = False  # type: ignore[index]
                # Re-synchronize a permission already resolved via the REST
                # endpoint (handles the rare race where the immediate UI update
                # could not be applied before tool_result/done streamed in).
                with contextlib.suppress(Exception):
                    self._sync_registry_approval(tool_call_id, parts, tool_idx)
            except Exception:
                pass
            return
        if etype == "permission_request":
            meta = _permission_meta_from_event(event)
            if meta is None:
                return
            tool_call_id = meta["tool_call_id"]
            idx = _ensure_assistant_message(self.controller)
            try:
                state = self.controller.state
                if state is None:
                    return
                messages = state["messages"]
                parts = messages[idx]["parts"]
                tool_idx = _find_tool_part_index(parts, tool_call_id)
                if tool_idx is None:
                    tool_name = _derive_tool_name(event)
                    args, args_text = _derive_tool_args(event)
                    tool_part: dict[str, Any] = {
                        "type": "tool-call",
                        "toolCallId": tool_call_id,
                        "toolName": tool_name,
                        "args": args,
                        "argsText": args_text,
                    }
                    parts.append(tool_part)
                    tool_idx = len(parts) - 1
                part = parts[tool_idx]
                unsupported = meta.get("unsupported_kinds") or []
                if unsupported:
                    # Unknown option kinds: never selectable, never assigned
                    # approved true/false. Log only short ids + kind, no payload.
                    log_event(
                        logger,
                        logging.WARNING,
                        "assistant_permission_option_unsupported",
                        session=short_id(self.session_key),
                        permission=short_id(meta["permission_id"]),
                        kinds=",".join(unsupported)[:64],
                    )
                # Always project an official approval so Assistant UI shows a
                # requires-action state. When there are no supported options we
                # attach an EMPTY option list plus a safe reason: the user can
                # only cancel the run (no fake Allow/Deny, no approved guess).
                existing = part.get("approval") if isinstance(part, dict) else None
                if not isinstance(existing, dict) or existing.get("approved") is None:
                    approval = {
                        "id": meta["permission_id"],
                        "options": meta["options"],
                    }
                    if not meta["options"]:
                        approval["reason"] = _UNSUPPORTED_PERMISSION_REASON
                    part["approval"] = approval
            except Exception:
                pass
            return

        if etype == "done":
            _set_status(self.controller, "complete")
            self.controller.flush()
            return
        if etype == "error":
            msg = event.get("message")
            safe = str(msg)[:200] if isinstance(msg, str) else "error"
            _set_status(self.controller, "error", error=safe)
            with contextlib.suppress(Exception):
                self.controller.add_error(safe)
            return
        if etype in {"tool_start", "tool_update", "tool_result", "raw", "part_delta"}:
            return
        if logger.isEnabledFor(logging.DEBUG):
            log_event(
                logger,
                logging.DEBUG,
                "assistant_unhandled_acp_event",
                session=short_id(self.session_key),
                event_type=str(etype),
            )

    def update_approval(self, permission_id: str, option_id: str, approved: bool) -> bool:
        """Set the chosen option and approved flag on the matching tool-call part.

        Returns False when the stream/session has already ended (no controller
        state) or the approval part is gone, so the caller can report an honest
        lifecycle conflict instead of claiming the approval was delivered.
        """
        try:
            state = self.controller.state
            if state is None:
                return False
            messages = state["messages"]
            for message in messages:
                parts = message.get("parts") if isinstance(message, dict) else None
                if not isinstance(parts, list):
                    continue
                for part in parts:
                    if not isinstance(part, dict) or part.get("type") != "tool-call":
                        continue
                    approval = part.get("approval")
                    if not isinstance(approval, dict):
                        continue
                    if approval.get("id") != permission_id:
                        continue
                    approval["optionId"] = option_id
                    approval["approved"] = approved
                    return True
            return False
        except Exception:
            return False
