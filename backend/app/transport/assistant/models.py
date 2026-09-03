"""Request and state models for the AssistantTransport endpoint.

Only the official request fields are modelled; nested payloads remain
``Any``/``dict`` so Python does not mirror the full TypeScript Assistant UI
type system.  State is deliberately minimal — a stable session identity plus
backend-native messages sufficient for the later frontend converter.

Backend dependency: PyPI ``assistant-stream==0.0.36`` (the Python server-side
streaming package). NOTE: the frontend pulls a *separate* npm package,
``assistant-stream@^0.3.40``, transitively via ``@assistant-ui/react``; the two
share a name but are different ecosystems with independent version lines, so a
PyPI version need not exist on npm and vice-versa. Do NOT replace the Python pin
with the npm version. Official API reference:
https://www.assistant-ui.com/docs/runtimes/custom/assistant-transport
- POST body: {state, commands, system, tools, threadId, parentId, callSettings, config}
- commands: [{type:"add-message", message:{role, parts:[{type:"text",text}]}, parentId, sourceId}]
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from ...agents.prompt_content import PromptValidationError, parse_inline_data_url


class AssistantTransportRequest(BaseModel):
    """Official AssistantTransport request shape.

    Field names mirror the spec verbatim (https://www.assistant-ui.com/docs/runtimes/custom/assistant-transport).
    """

    state: Any | None = None
    commands: list[Any] = Field(default_factory=list)
    system: Any | None = None
    tools: Any | None = None
    threadId: str | None = None
    parentId: str | None = None
    callSettings: Any | None = None
    config: Any | None = None

    model_config = {"extra": "allow"}


def ensure_state_shape(
    raw: Any | None, *, thread_id: str | None
) -> tuple[dict[str, Any], str, bool]:
    """Return (state, session_id, is_new).

    Priority: ``state.sessionId`` → ``request.threadId`` → newly generated UUID.
    When a UUID is generated it is stored immediately in ``state.sessionId`` so
    the next request can return that state and reconnect to the same adapter.
    Only ``sessionId`` (camelCase) is used; ``session_id`` mirror removed.
    """
    if not isinstance(raw, dict):
        raw = {}
    state: dict[str, Any] = dict(raw)

    session_id: str | None = None
    raw_sid = state.get("sessionId")
    if isinstance(raw_sid, str) and raw_sid.strip():
        session_id = raw_sid.strip()
        is_new = False
    elif isinstance(thread_id, str) and thread_id.strip():
        session_id = thread_id.strip()
        is_new = False
    else:
        session_id = str(uuid.uuid4())
        is_new = True

    state["sessionId"] = session_id

    messages = state.get("messages")
    if not isinstance(messages, list):
        messages = []
        state["messages"] = messages

    status = state.get("status")
    if not isinstance(status, str) or not status:
        state["status"] = "ready"

    return state, session_id, is_new


def _extract_text_from_message(message: dict[str, Any]) -> str | None:
    """Extract concatenated text from official message.parts."""
    parts = message.get("parts")
    if not isinstance(parts, list):
        return None
    texts: list[str] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        if part.get("type") != "text":
            continue
        text = part.get("text")
        if isinstance(text, str) and text:
            texts.append(text)
    if not texts:
        return None
    joined = "\n".join(texts)
    return joined if joined.strip() else None


def _validate_message_shape(message: Any) -> dict[str, Any]:
    """Validate official message shape and return a shallow copy.

    Official pinned source (assistant-ui docs + examples):
    message is a ThreadMessage-like object with at least
    {role, parts[]} where parts are {type:"text", text}.  We validate
    required fields strictly and preserve optional id/sourceId as-is.
    """
    if not isinstance(message, dict):
        raise ValueError("message must be an object")
    role = message.get("role")
    if role != "user":
        # Phase 1 only handles user messages; still enforce official role set
        if role not in {"user", "assistant", "system"}:
            raise ValueError("message.role must be 'user'|'assistant'|'system'")
        if role != "user":
            raise ValueError("only user messages are accepted in Phase 1")
    parts = message.get("parts")
    if not isinstance(parts, list) or not parts:
        raise ValueError("message.parts must be a non-empty list")
    for part in parts:
        if not isinstance(part, dict):
            raise ValueError("message.parts entries must be objects")
        ptype = part.get("type")
        if ptype == "text":
            text = part.get("text")
            if not isinstance(text, str):
                raise ValueError("text part must have string text")
        elif ptype == "image":
            img = part.get("image")
            if not isinstance(img, str) or not img.strip():
                raise ValueError("image part must carry a non-empty 'image' data URL")
            # Strict data: URL + explicit image MIME allowlist (shared parser).
            # Rejects malformed/unsupported pre-stream so the client gets a clean
            # HTTP 400 instead of a mid-stream failure.
            try:
                parse_inline_data_url(img)
            except PromptValidationError as exc:
                raise ValueError(f"invalid image part: {exc}") from exc
        else:
            # Only text and image parts are produced by the registered official
            # attachment adapter (SimpleImageAttachmentAdapter, accept="image/*").
            # Reject unknown part types pre-stream so the client gets a clean 400
            # instead of a mid-stream failure.
            raise ValueError(f"unsupported message part type: {ptype!r}")
    return dict(message)


# --- RTAI capability custom commands (official AssistantTransport extension) ---
# Namespaced command identifiers. Strict Pydantic validation yields FastAPI's
# standard 422 for schema violations (missing/non-string/blank/oversized IDs,
# aliases, extra fields). Unknown or unsupported selection IDs are handled at
# execution time via a safe transport error in state, because the adapter is the
# authoritative owner of the valid option set and is not constructed pre-stream.

RTAI_REFRESH_COMMAND = "rtai.refreshCapabilities"
RTAI_SELECT_COMMANDS: dict[str, str] = {
    "rtai.selectAgent": "agent",
    "rtai.selectModel": "model",
    "rtai.selectMode": "mode",
    "rtai.selectThinking": "thinking",
}

RTAI_CLIENT_DIAGNOSTIC_COMMAND = "rtai.clientDiagnostic"


class RtaiRefreshCapabilitiesCommand(BaseModel):
    """Strict refresh-capabilities custom command."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["rtai.refreshCapabilities"]


class RtaiSelectCommand(BaseModel):
    """Strict capability-selection custom command (no optimistic claim)."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["rtai.selectAgent", "rtai.selectModel", "rtai.selectMode", "rtai.selectThinking"]
    value: str = Field(min_length=1, max_length=256)

    @field_validator("value")
    @classmethod
    def _reject_blank_value(cls, v: str) -> str:
        # Reject whitespace-only IDs without altering valid ones. The original
        # value is returned byte-for-byte so adapter IDs (exact, case-sensitive)
        # are never trimmed, lowercased, or normalized. Missing/non-string/empty/
        # oversized/extra fields remain standard 422 via Pydantic.
        if v.strip() == "":
            raise ValueError("value must not be blank")
        return v


class RtaiClientDiagnosticCommand(BaseModel):
    """Strict client diagnostics custom command (single authoritative stream).

    Frontend lifecycle moments are reported through this command over the existing
    AssistantTransport command path. Only safe, bounded scalar metadata is accepted:
    an event enum, an optional kind enum, and an optional option-length count.
    Anything else (raw identifiers, session/option ids, prompt text, tool data,
    file/path data, tokens, credentials, free-form detail) is rejected via
    ``extra="forbid"`` and the Pydantic standard 422.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["rtai.clientDiagnostic"]
    event: Literal[
        "gate_ready",
        "capability_command_sent",
        "model_command_sent",
        "permission_post_initiated",
        "client_error",
    ]
    kind: Literal[
        "refresh",
        "agent",
        "model",
        "mode",
        "thinking",
        "transport",
        "permission",
    ] | None = None
    optionLength: int | None = Field(default=None, ge=0, le=256)

    @model_validator(mode="after")
    def _enforce_option_length_scope(self) -> "RtaiClientDiagnosticCommand":
        # optionLength is only meaningful for the permission POST-initiated event;
        # reject it on every other event so no length/identifier leaks via it.
        if self.optionLength is not None and self.event != "permission_post_initiated":
            raise ValueError(
                "optionLength is only allowed for permission_post_initiated"
            )
        return self


def _validate_rtai_command(model: type[BaseModel], cmd: dict[str, Any], idx: int) -> None:
    """Validate a custom command; on failure raise FastAPI's standard 422."""
    try:
        model.model_validate(cmd)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors(), body=cmd) from None


def _find_parent_index(messages: list[Any], parent_id: str) -> int | None:
    """Return the index of the message whose stable ``id`` equals ``parent_id``.

    ``messages`` is a plain list of JSON message dicts (a shallow copy of the
    request state, or the current snapshot produced by iterating a StateProxy,
    which yields the underlying plain dicts). Each entry must itself be a dict
    exposing an ``id`` string. Shared by pre-stream validation and runtime
    application so parent lookup/truncation use one semantics.
    """
    for i, m in enumerate(messages):
        if isinstance(m, dict):
            mid = m.get("id")
            if isinstance(mid, str) and mid == parent_id:
                return i
    return None


def prepare_validated_commands(
    initial_messages: list[Any],
    commands: list[Any],
) -> list[dict[str, Any]]:
    """Validate and prepare official add-message commands before streaming.

    Simulates commands in order against a temporary message list:
    - validates message.role/parts/parentId/sourceId
    - if parentId is non-null, locates that ID in the simulated list
    - truncates after parent
    - ensures each new message has a stable UUID (preserve incoming id if present)
    - allows later command to reference earlier prepared message
    Raises HTTPException(400) before DataStreamResponse if validation fails.
    """
    from fastapi import HTTPException

    # Shallow copy of initial messages for simulation
    simulated: list[dict[str, Any]] = []
    for m in initial_messages:
        if isinstance(m, dict):
            simulated.append(dict(m))
        else:
            # If state was proxied or other, store as-is
            simulated.append(m)  # type: ignore[arg-type]

    prepared: list[dict[str, Any]] = []

    # Order policy (enforced before streaming, so the client gets a clean HTTP 400
    # rather than a mid-stream error):
    #   * capability-only batches: allowed;
    #   * add-message-only batches: allowed;
    #   * zero or more capability commands followed by one or more consecutive
    #     add-message commands: allowed (capability changes affect this prompt);
    #   * once the first add-message appears, any later capability command: rejected
    #     with 400 unsupported_command_order.
    # The prepared list is never silently reordered, deferred, duplicated, or dropped.
    saw_add_message = False
    for idx, cmd in enumerate(commands):
        if not isinstance(cmd, dict):
            raise HTTPException(status_code=400, detail={"error": "invalid_command", "index": idx})
        ctype = cmd.get("type")
        if ctype == "add-message":
            saw_add_message = True
        elif ctype == RTAI_REFRESH_COMMAND:
            if saw_add_message:
                raise HTTPException(
                    status_code=400,
                    detail={"error": "unsupported_command_order"},
                )
            _validate_rtai_command(RtaiRefreshCapabilitiesCommand, cmd, idx)
            prepared.append({"type": RTAI_REFRESH_COMMAND})
            continue
        elif ctype in RTAI_SELECT_COMMANDS:
            if saw_add_message:
                raise HTTPException(
                    status_code=400,
                    detail={"error": "unsupported_command_order"},
                )
            _validate_rtai_command(RtaiSelectCommand, cmd, idx)
            prepared.append({"type": ctype, "value": cmd["value"]})
            continue
        elif ctype == RTAI_CLIENT_DIAGNOSTIC_COMMAND:
            # Safe, non-mutating diagnostic ping. Strictly validated
            # (extra="forbid", enum-only event/kind, bounded optionLength) and
            # carried through the same command path as other rtai.* commands.
            # Allowed at any position: it never affects the prompt, so it bypasses
            # the add-message order policy that gates capability selections.
            _validate_rtai_command(RtaiClientDiagnosticCommand, cmd, idx)
            prepared.append(
                {
                    "type": RTAI_CLIENT_DIAGNOSTIC_COMMAND,
                    "event": cmd["event"],
                    "kind": cmd.get("kind"),
                    "optionLength": cmd.get("optionLength"),
                }
            )
            continue
        else:
            raise HTTPException(
                status_code=400, detail={"error": "unsupported_command_type", "type": ctype}
            )

        raw_message = cmd.get("message")
        try:
            validated_msg = _validate_message_shape(raw_message)
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail={"error": "invalid_message", "reason": str(exc)}
            ) from None

        parent_id = cmd.get("parentId")
        source_id = cmd.get("sourceId")
        # Validate parentId/sourceId types per official contract
        if parent_id is not None and not isinstance(parent_id, str):
            raise HTTPException(status_code=400, detail={"error": "invalid_parentId"})
        if source_id is not None and not isinstance(source_id, str):
            raise HTTPException(status_code=400, detail={"error": "invalid_sourceId"})

        # parentId truncation simulation
        if isinstance(parent_id, str) and parent_id:
            parent_idx = _find_parent_index(simulated, parent_id)
            if parent_idx is None:
                raise HTTPException(
                    status_code=400, detail={"error": "parent_not_found", "parentId": parent_id}
                )
            # Truncate after parent
            simulated = simulated[: parent_idx + 1]

        # Ensure stable message ID: preserve official incoming id if present
        msg_id = validated_msg.get("id")
        if not isinstance(msg_id, str) or not msg_id.strip():
            # Also check alternative official field? Only 'id' is official per pinned source
            msg_id = str(uuid.uuid4())
            validated_msg["id"] = msg_id
        else:
            validated_msg["id"] = msg_id.strip()
            msg_id = validated_msg["id"]

        # Store generated/preserved ID and preserve sourceId per contract (do not use as new id)
        # Build prepared command copy with stable message
        prepared_cmd: dict[str, Any] = {
            "type": "add-message",
            "message": validated_msg,
            "parentId": parent_id,
            "sourceId": source_id,
        }
        # Preserve any extra official fields? Only these four are official; ignore others
        prepared.append(prepared_cmd)
        simulated.append(validated_msg)

    return prepared
