"""Protocol v1 WebSocket and HTTP routes.

Each incoming WebSocket gets its own adapter instance, its own sequence
counters, and its own permission tracker.  Cleanup always targets only
the handle this connection created — never another caller's process.

Chat history (Phase 5): each connection is assigned a server-generated RTAI
session id; the database session is created only after the project path and
adapter are validated, and trusted normalized conversation events are
persisted in order through the ``emit()`` boundary. Persistence failures are
reported once and degrade gracefully without stopping the live stream.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect

from ..agents.base import AgentAdapter
from ..agents.capabilities import AttachmentCapabilities, SessionCapabilities
from ..core.protocol import resolve_project_path
from ..history.errors import CursorValidationError
from ..history.models import HistoryEvent, HistorySession, SessionStatus
from ..history.sanitize import (
    build_event_key,
    event_discriminator,
    is_persistable,
    sanitize_event_payload,
)
from ..logging_config import log_event, short_id
from .protocol_v1 import (
    PROTOCOL_VERSION,
    normalize_emission,
    snapshot_to_v1_events,
    validate_command,
)

router = APIRouter()

logger = logging.getLogger(__name__)

_SESSION_LIST_LIMIT = 50
_EVENT_LIST_LIMIT = 200
#: Hard page-size bounds (mirror the repository's defensive bounds).
_SESSION_LIST_MAX = 200
_EVENT_LIST_MAX = 500


@router.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Chat history REST read APIs (Phase 5). Registered before the /api catch-all
# and the SPA static mount so they are never intercepted.
# ---------------------------------------------------------------------------


def _repo(request: Request):
    return getattr(request.app.state, "history_repository", None)


def _bad_request(code: str, message: str) -> HTTPException:
    """Normalized JSON 400 error: ``{"error": {"code": ..., "message": ...}}``."""
    return HTTPException(status_code=400, detail={"error": {"code": code, "message": message}})


def _parse_limit(raw: str | None, default: int, maximum: int) -> int:
    """Validate a client-supplied ``limit``, returning 400 on any invalid value.

    ``limit`` is accepted as a raw string so non-numeric input is rejected with
    the normalized 400 error rather than FastAPI's automatic 422. Invalid
    values are never silently clamped.
    """
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise _bad_request(
            "invalid_limit", f"limit must be an integer between 1 and {maximum}"
        ) from None
    if not 1 <= value <= maximum:
        raise _bad_request("invalid_limit", f"limit must be an integer between 1 and {maximum}")
    return value


@router.get("/api/sessions")
async def list_sessions(
    request: Request,
    cursor: str | None = Query(default=None),
    limit: str | None = Query(default=None),
) -> dict[str, Any]:
    repo = _repo(request)
    if repo is None:
        raise HTTPException(status_code=503, detail={"error": "history_unavailable"})
    page_limit = _parse_limit(limit, _SESSION_LIST_LIMIT, _SESSION_LIST_MAX)
    try:
        items, next_cursor = repo.list_sessions(cursor=cursor, limit=page_limit)
    except CursorValidationError as exc:
        raise _bad_request("invalid_cursor", str(exc)) from None
    return {
        "sessions": [_session_dict(s) for s in items],
        "next_cursor": next_cursor,
    }


@router.get("/api/sessions/{session_id}")
async def get_session(request: Request, session_id: str) -> dict[str, Any]:
    repo = _repo(request)
    if repo is None:
        raise HTTPException(status_code=503, detail={"error": "history_unavailable"})
    session = repo.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail={"error": "session_not_found"})
    return _session_dict(session)


@router.get("/api/sessions/{session_id}/events")
async def get_session_events(
    request: Request,
    session_id: str,
    cursor: str | None = Query(default=None),
    limit: str | None = Query(default=None),
) -> dict[str, Any]:
    repo = _repo(request)
    if repo is None:
        raise HTTPException(status_code=503, detail={"error": "history_unavailable"})
    if repo.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail={"error": "session_not_found"})
    page_limit = _parse_limit(limit, _EVENT_LIST_LIMIT, _EVENT_LIST_MAX)
    try:
        items, next_cursor = repo.get_events(session_id, cursor=cursor, limit=page_limit)
    except CursorValidationError as exc:
        raise _bad_request("invalid_cursor", str(exc)) from None
    return {
        "events": [_event_dict(e) for e in items],
        "next_cursor": next_cursor,
    }


def _session_dict(session: HistorySession) -> dict[str, Any]:
    return {
        "session_id": session.rtai_session_id,
        "adapter_kind": session.adapter_kind,
        "native_session_id": session.native_session_id,
        "cwd": session.cwd,
        "user_title": session.user_title,
        "provider_title": session.provider_title,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "last_turn_at": session.last_turn_at,
        "status": session.status.value,
        "resume_capable": session.resume_capable,
        "resume_reason": session.resume_reason,
    }


def _event_dict(event: HistoryEvent) -> dict[str, Any]:
    return {
        "event_ordinal": event.event_ordinal,
        "event_type": event.event_type,
        "payload": event.payload,
        "turn_id": event.turn_id,
        "message_id": event.message_id,
        "sequence": event.sequence,
        "timestamp": event.timestamp,
        "created_at": event.created_at,
    }


# ---------------------------------------------------------------------------
# WebSocket chat handler
# ---------------------------------------------------------------------------


@router.websocket("/ws")
async def chat_socket(websocket: WebSocket, cwd: str | None = Query(default=None)) -> None:
    await websocket.accept()
    log_event(logger, logging.INFO, "ws_accepted", cwd=cwd or "not_provided")
    send_lock = asyncio.Lock()

    # Server-assigned RTAI session id, generated on accept. The database
    # session is created later, once the project path and adapter are
    # validated. Never derived from the client-supplied turn_ctx session id.
    rtai_session_id = str(uuid.uuid4())
    # Once True, persistence is disabled for the rest of the connection and
    # diagnostics bypass persistence entirely (no recursion).
    persist_failed = False

    # Correlation aliases for the active turn; updated by the prompt branch.
    turn_ctx: dict[str, str] = {}
    # Monotonic per-turn sequence counter for streaming deltas.
    delta_seq = 0
    # Session-local occurrence counters for event families that repeat without
    # a wire sequence (part_delta chunks per part, tool_update per tool). These
    # are persistence-only identity values; they are never sent on the wire.
    part_delta_occurrence: dict[tuple[str, str], int] = {}
    tool_update_occurrence: dict[tuple[str, str], int] = {}

    async def _persist_frame(frame: dict[str, Any]) -> None:
        """Persist one trusted normalized frame (best-effort, thread-safe)."""
        repo = getattr(websocket.app.state, "history_repository", None)
        if repo is None:
            return
        event_type = str(frame.get("type") or "")
        if not is_persistable(event_type):
            return
        payload = sanitize_event_payload(frame)
        if not payload:
            return
        # Identity: the protocol sequence where one exists, otherwise a
        # deterministic session-local occurrence value for families that
        # repeat without a wire sequence. Computed here, before the DB write,
        # so a retry of the same operation reuses the same key.
        sequence = frame.get("sequence")
        if event_type == "part_delta":
            part_key = (str(frame.get("turn_id") or ""), str(frame.get("part_id") or ""))
            part_delta_occurrence[part_key] = part_delta_occurrence.get(part_key, 0) + 1
            sequence = part_delta_occurrence[part_key]
        elif event_type == "tool_update":
            tool_key = (str(frame.get("turn_id") or ""), str(frame.get("tool_call_id") or ""))
            tool_update_occurrence[tool_key] = tool_update_occurrence.get(tool_key, 0) + 1
            sequence = tool_update_occurrence[tool_key]
        event = HistoryEvent(
            rtai_session_id=rtai_session_id,
            event_type=event_type,
            event_key=build_event_key(
                event_type,
                frame.get("turn_id"),
                frame.get("message_id"),
                sequence,
                event_discriminator(event_type, frame),
            ),
            payload=payload,
            turn_id=frame.get("turn_id"),
            message_id=frame.get("message_id"),
            sequence=frame.get("sequence"),
            timestamp=frame.get("timestamp"),
            created_at=int(time.time() * 1000),
        )
        # Run the synchronous SQLite write off the event loop.
        await asyncio.to_thread(repo.append_event, event)

    async def emit(raw: dict[str, Any], *, persist: bool = True) -> None:
        """Send a Protocol v1 frame with the authoritative envelope.

        ``protocol_version`` is injected here so every outbound frame carries
        the v1 marker the frontend requires.  The field is set after the raw
        payload is copied so adapter-provided values cannot override it.
        """
        nonlocal delta_seq, persist_failed
        session_id = turn_ctx.get("session_id", "")
        if session_id:
            # Wrap with the authoritative envelope (session_id, turn_id,
            # timestamp, and a per-turn sequence for deltas) so streaming
            # events carry the correlation fields the frontend requires.
            if raw.get("type") == "delta":
                delta_seq += 1
            frame = normalize_emission(
                raw,
                session_id=session_id,
                turn_id=turn_ctx.get("turn_id"),
                sequence=delta_seq,
            )
        else:
            # No active turn yet (status/capability/error frames): keep the
            # frame minimal, just the protocol marker.
            frame = dict(raw)
            frame["protocol_version"] = PROTOCOL_VERSION
        event_type = str(frame.get("type") or "unknown")
        content_length: int | None = None
        if logger.isEnabledFor(logging.DEBUG):
            content_length = len(json.dumps(frame, default=str))
            log_event(
                logger,
                logging.DEBUG,
                "adapter_event_received",
                event_type=event_type,
                length=content_length,
            )
            log_event(
                logger,
                logging.DEBUG,
                "event_normalized",
                event_type=event_type,
                length=content_length,
            )

        # Persist trusted conversation events in order. On failure, report a
        # one-time diagnostic that bypasses persistence (no recursion) and
        # keep the live stream running in degraded mode.
        if persist and not persist_failed:
            try:
                await _persist_frame(frame)
            except Exception:
                persist_failed = True
                log_event(logger, logging.ERROR, "history_persist_failed")
                await emit(
                    {
                        "type": "error",
                        "message": ("History persistence failed; continuing without saving."),
                        "code": "history_degraded",
                    },
                    persist=False,
                )

        async with send_lock:
            await websocket.send_json(frame)
        if logger.isEnabledFor(logging.DEBUG):
            log_event(
                logger,
                logging.DEBUG,
                "websocket_event_sent",
                event_type=event_type,
                length=content_length,
            )
        if event_type in ("done", "error"):
            log_event(
                logger,
                logging.INFO,
                "terminal_event_received",
                event_type=event_type,
                session=short_id(turn_ctx.get("session_id")),
                turn=short_id(turn_ctx.get("turn_id")),
            )
            if event_type == "done":
                log_event(
                    logger,
                    logging.INFO,
                    "turn_finalized",
                    session=short_id(turn_ctx.get("session_id")),
                    turn=short_id(turn_ctx.get("turn_id")),
                )

    # Track whether we created a temporary session dir (for cleanup later).
    session_dir: Path | None = None

    # Validate project path early so we can reject before creating the adapter.
    project: Path | None = None
    try:
        # If no cwd provided, create a temporary scratch folder for the agent.
        # This lets chat mode work without a pre-selected project folder.
        if cwd is None:
            import tempfile

            session_dir = Path(tempfile.mkdtemp(prefix="rtai-session-"))
            cwd = str(session_dir)
        project = resolve_project_path(cwd)
    except ValueError as exc:
        if str(exc) == "project_folder_not_provided":
            log_event(logger, logging.INFO, "project_folder_missing")
            # No cwd supplied and no RTAI_PROJECT_ROOT configured — keep the
            # WebSocket open so the UI can prompt the user for a folder.
            await emit(
                {
                    "type": "error",
                    "message": (
                        "No project folder specified. Enter a valid folder path "
                        "in the control bar, or set RTAI_PROJECT_ROOT."
                    ),
                    "code": "project_folder_not_provided",
                }
            )
            # Stay in a holding loop until the client disconnects.
            while True:
                raw = await websocket.receive_json()
                if not isinstance(raw, dict):
                    continue
                kind = raw.get("type")
                if kind == "prompt":
                    await emit(
                        {
                            "type": "command_result",
                            "request_id": raw.get("request_id"),
                            "command": "prompt",
                            "success": False,
                            "message": "project_folder_not_provided",
                        }
                    )
                elif kind in (
                    "cancel",
                    "select_agent",
                    "select_model",
                    "select_mode",
                    "set_thinking",
                    "permission_response",
                ):
                    await emit(
                        {
                            "type": "command_result",
                            "request_id": raw.get("request_id"),
                            "command": kind,
                            "success": False,
                            "message": "project_folder_not_provided",
                        }
                    )
                # Ignore everything else; wait for the user to change the folder
                # and reconnect (which will create a fresh connection with the
                # new cwd).
            return
        else:
            log_event(logger, logging.INFO, "invalid_cwd", reason="invalid_cwd")
            await emit({"type": "error", "message": str(exc), "code": "invalid_cwd"})
            await websocket.close(code=1008)
            return

    adapter: AgentAdapter = websocket.app.state.adapter_factory.create()
    prompt_task: asyncio.Task | None = None

    try:
        # Create the database session now that the project path and adapter
        # are validated, before the first normalized session event.
        repo = getattr(websocket.app.state, "history_repository", None)
        if repo is not None:
            now = int(time.time() * 1000)
            adapter_kind = adapter.capability_snapshot().source
            repo.create_session(
                HistorySession(
                    rtai_session_id=rtai_session_id,
                    adapter_kind=adapter_kind,
                    cwd=str(project),
                    created_at=now,
                    updated_at=now,
                )
            )
            log_event(
                logger,
                logging.INFO,
                "history_session_created",
                session=short_id(rtai_session_id),
            )

        await emit({"type": "status", "state": "starting", "cwd": str(project)})
        await adapter.start(project, emit)
        log_event(logger, logging.INFO, "adapter_started")

        # Record the provider's native session id and resume capability state.
        if repo is not None:
            native_id = None
            owned = adapter.owned_process()
            if owned is not None:
                native_id = owned.session_id
            snap = adapter.capability_snapshot()
            resume_capable: bool | None = None
            resume_reason: str | None = None
            sessions_cap = getattr(snap, "sessions", None)
            if isinstance(sessions_cap, SessionCapabilities):
                resume_capable = sessions_cap.resume
                if resume_capable is None:
                    resume_reason = "resume capability not advertised"
            else:
                resume_reason = "session capabilities unavailable"
            if native_id:
                repo.record_native_mapping(
                    rtai_session_id,
                    native_id,
                    adapter_kind=snap.source,
                    resume_capable=resume_capable,
                    resume_reason=resume_reason,
                )
                log_event(
                    logger,
                    logging.INFO,
                    "history_native_mapped",
                    session=short_id(rtai_session_id),
                    native=short_id(native_id),
                )

        # Emit authoritative capability events before marking ready.
        snap = adapter.capability_snapshot()
        for event in snapshot_to_v1_events(snap):
            await emit(event)
        log_event(logger, logging.INFO, "capabilities_emitted")

        await emit({"type": "status", "state": "ready", "cwd": str(project)})
        log_event(logger, logging.INFO, "connection_ready")

        while True:
            raw = await websocket.receive_json()
            if not isinstance(raw, dict):
                await emit({"type": "error", "message": "expected JSON object"})
                continue

            kind = raw.get("type")

            # ---- prompt ----
            if kind == "prompt":
                ok, err = validate_command(raw)
                if not ok:
                    log_event(
                        logger,
                        logging.INFO,
                        "command_validated",
                        command="prompt",
                        valid=False,
                        reason=err,
                    )
                    await emit(
                        {
                            "type": "command_result",
                            "request_id": raw.get("request_id"),
                            "command": "prompt",
                            "success": False,
                            "message": err,
                        }
                    )
                    continue
                log_event(
                    logger,
                    logging.INFO,
                    "command_validated",
                    command="prompt",
                    valid=True,
                )
                if prompt_task and not prompt_task.done():
                    log_event(logger, logging.INFO, "prompt_rejected_busy")
                    await emit(
                        {
                            "type": "command_result",
                            "request_id": raw.get("request_id"),
                            "command": "prompt",
                            "success": False,
                            "message": "A response is already running",
                        }
                    )
                    continue
                session_id: str = raw["session_id"]
                turn_id: str = raw["turn_id"]
                msg_id: str = raw["message_id"]
                text: str | None = raw.get("text")
                prompt_blocks_raw: list[Any] | None = raw.get("prompt")
                turn_ctx.update(
                    session_id=session_id,
                    turn_id=turn_id,
                    message_id=msg_id,
                    request_id=str(raw.get("request_id") or ""),
                )
                delta_seq = 0
                log_event(
                    logger,
                    logging.INFO,
                    "prompt_received",
                    session=short_id(session_id),
                    turn=short_id(turn_id),
                    message=short_id(msg_id),
                    request=short_id(raw.get("request_id")),
                    text_length=len(text) if text else None,
                    block_count=len(prompt_blocks_raw) if prompt_blocks_raw else None,
                )

                async def _turn(
                    _text: str | None = text,
                    _prompt_blocks_raw: list[Any] | None = prompt_blocks_raw,
                    _session_id: str = session_id,
                    _turn_id: str = turn_id,
                ) -> None:
                    try:
                        log_event(
                            logger,
                            logging.INFO,
                            "adapter_prompt_started",
                            session=short_id(_session_id),
                            turn=short_id(_turn_id),
                        )
                        if _prompt_blocks_raw is not None:
                            # Multi-block path with attachment support.
                            from ..agents.acp.prompt_content import (
                                make_prompt_content,
                                validate_prompt_limits,
                            )

                            snap = adapter.capability_snapshot()
                            ac = snap.attachments
                            if isinstance(ac, AttachmentCapabilities):
                                if ac.block_types:
                                    # Validate and convert blocks.
                                    blocks = [
                                        make_prompt_content(dict(b)) for b in _prompt_blocks_raw
                                    ]
                                    validate_prompt_limits(
                                        blocks,
                                        max_item_bytes=ac.max_item_bytes,
                                        max_total_bytes=ac.max_total_bytes,
                                        max_count=ac.max_count,
                                    )
                                    # Check each block against negotiated capabilities.
                                    kind_map = {
                                        "image": "images",
                                        "audio": "audio",
                                        "embedded_text": "embedded_resources",
                                        "embedded_blob": "embedded_resources",
                                    }
                                    for b in blocks:
                                        attr = kind_map.get(b.kind.value)
                                        if attr and attr in vars(ac) and not getattr(ac, attr):
                                            raise RuntimeError(
                                                f"attachment rejected: {b.kind.value} "
                                                f"not supported by this agent"
                                            )
                                    await adapter.submit_prompt_content(blocks)
                                else:
                                    # Provider advertises no attachment types — fall back
                                    # to text-only if the only block is text.
                                    if (
                                        len(_prompt_blocks_raw) == 1
                                        and _prompt_blocks_raw[0].get("kind") == "text"
                                    ):
                                        await adapter.submit_prompt(
                                            _prompt_blocks_raw[0].get("text", "") or ""
                                        )
                                    else:
                                        raise RuntimeError(
                                            "attachments not supported by this agent"
                                        )
                            else:
                                # Attachments unavailable — only text prompts allowed.
                                if (
                                    len(_prompt_blocks_raw) == 1
                                    and _prompt_blocks_raw[0].get("kind") == "text"
                                ):
                                    await adapter.submit_prompt(
                                        _prompt_blocks_raw[0].get("text", "") or ""
                                    )
                                else:
                                    raise RuntimeError("attachments not available for this agent")
                        else:
                            # Legacy text-only path.
                            if not _text:
                                raise RuntimeError("text is required when prompt is not provided")
                            await adapter.submit_prompt(_text)
                        # Task completes when submit_prompt returns: all deltas sent,
                        # done emitted, prompt() awaited. No sleep needed.
                    except asyncio.CancelledError:
                        log_event(
                            logger,
                            logging.INFO,
                            "turn_cancelled",
                            session=short_id(_session_id),
                            turn=short_id(_turn_id),
                        )
                        await emit(
                            {
                                "type": "done",
                                "session_id": _session_id,
                                "turn_id": _turn_id,
                                "reason": "cancelled",
                            }
                        )
                        raise
                    except Exception as exc:
                        log_event(
                            logger,
                            logging.ERROR,
                            "turn_failed",
                            session=short_id(_session_id),
                            turn=short_id(_turn_id),
                            error=type(exc).__name__,
                        )
                        await emit(
                            {
                                "type": "error",
                                "session_id": _session_id,
                                "turn_id": _turn_id,
                                "message": str(exc),
                            }
                        )

                prompt_task = asyncio.create_task(_turn())
                # Emit user_message so the UI binds the response window. This
                # is the single persistence point for the user's message — it
                # travels through the trusted emit() boundary exactly once.
                user_msg: dict[str, Any] = {
                    "type": "user_message",
                    "session_id": session_id,
                    "turn_id": turn_id,
                    "message_id": msg_id,
                }
                if text is not None:
                    user_msg["text"] = text
                if prompt_blocks_raw is not None:
                    # Include safe attachment metadata (no raw content).
                    user_msg["prompt"] = [
                        {
                            "kind": b.get("kind"),
                            "name": b.get("name", ""),
                            "mime_type": b.get("mime_type"),
                            "size_bytes": (
                                len(b.get("data_base64", ""))
                                if b.get("data_base64")
                                else (len(b.get("text", "")) if b.get("text") else None)
                            ),
                        }
                        for b in prompt_blocks_raw
                    ]
                await emit(user_msg)
                await emit(
                    {
                        "type": "command_result",
                        "request_id": raw["request_id"],
                        "command": "prompt",
                        "success": True,
                    }
                )
                continue

            # ---- cancel ----
            if kind == "cancel":
                ok, err = validate_command(raw)
                if not ok:
                    log_event(
                        logger,
                        logging.INFO,
                        "command_validated",
                        command="cancel",
                        valid=False,
                        reason=err,
                    )
                    await emit(
                        {
                            "type": "command_result",
                            "request_id": raw.get("request_id"),
                            "command": "cancel",
                            "success": False,
                            "message": err,
                        }
                    )
                    continue
                log_event(
                    logger,
                    logging.INFO,
                    "cancellation_requested",
                    session=short_id(raw.get("session_id")),
                    turn=short_id(raw.get("turn_id")),
                )
                await adapter.cancel()
                if prompt_task and not prompt_task.done():
                    prompt_task.cancel()
                await emit(
                    {
                        "type": "command_result",
                        "request_id": raw["request_id"],
                        "command": "cancel",
                        "success": True,
                    }
                )
                continue

            # ---- selection commands ----
            if kind in ("select_agent", "select_model", "select_mode", "set_thinking"):
                ok, err = validate_command(raw)
                if not ok:
                    log_event(
                        logger,
                        logging.INFO,
                        "command_validated",
                        command=kind,
                        valid=False,
                        reason=err,
                    )
                    await emit(
                        {
                            "type": "command_result",
                            "request_id": raw.get("request_id"),
                            "command": kind,
                            "success": False,
                            "message": err,
                        }
                    )
                    continue
                selection_kind = kind.removeprefix("select_")
                if kind == "select_agent":
                    value_id = raw.get("agent_id", "")
                elif kind == "select_model":
                    value_id = raw.get("model_id", "")
                elif kind == "select_mode":
                    value_id = raw.get("mode_id", "")
                else:
                    value_id = raw.get("level", "")
                log_event(
                    logger,
                    logging.INFO,
                    "selection_requested",
                    kind=selection_kind,
                    value_id=short_id(value_id),
                )
                result = await adapter.select(selection_kind, value_id or "")
                # Emit the authoritative selected-state event only when the
                # adapter actually applied the selection; a rejected value must
                # never be recorded by the UI (e.g. an unknown agent id).
                if result.applied:
                    selected_event: dict[str, Any] = {
                        "type": f"{selection_kind}_selected",
                        "session_id": raw["session_id"],
                    }
                    if kind == "select_agent":
                        selected_event["agent_id"] = value_id
                    elif kind == "select_model":
                        selected_event["model_id"] = value_id
                        # Refresh thinking if model-specific levels changed.
                        snap2 = adapter.capability_snapshot()
                        for ev in snapshot_to_v1_events(snap2):
                            if ev.get("type") == "thinking_available":
                                await emit(ev)
                                break
                    elif kind == "select_mode":
                        selected_event["mode_id"] = value_id
                    elif kind == "set_thinking":
                        selected_event["level"] = value_id
                    await emit(selected_event)
                await emit(
                    {
                        "type": "command_result",
                        "request_id": raw["request_id"],
                        "command": kind,
                        "success": result.applied,
                        "message": result.message,
                    }
                )
                continue

            # ---- permission_response ----
            if kind == "permission_response":
                ok, err = validate_command(raw)
                if not ok:
                    log_event(
                        logger,
                        logging.INFO,
                        "command_validated",
                        command="permission_response",
                        valid=False,
                        reason=err,
                    )
                    await emit(
                        {
                            "type": "command_result",
                            "request_id": raw.get("request_id"),
                            "command": "permission_response",
                            "success": False,
                            "message": err,
                        }
                    )
                    continue
                pid = raw["permission_request_id"]
                option_id = raw["option_id"]
                log_event(
                    logger,
                    logging.INFO,
                    "permission_response_received",
                    permission=short_id(pid),
                    option_id=short_id(option_id),
                )
                # Try the adapter's built-in handler first (ACP adapter).
                resolved = False
                if hasattr(adapter, "respond_to_permission"):
                    resolved = await adapter.respond_to_permission(pid, option_id)
                await emit(
                    {
                        "type": "permission_result",
                        "session_id": raw["session_id"],
                        "turn_id": raw["turn_id"],
                        "permission_request_id": pid,
                        "option_id": option_id,
                    }
                )
                await emit(
                    {
                        "type": "command_result",
                        "request_id": raw["request_id"],
                        "command": "permission_response",
                        "success": resolved,
                    }
                )
                continue

            # Unknown command — acknowledge failure if request_id present.
            if raw.get("request_id"):
                log_event(
                    logger,
                    logging.INFO,
                    "malformed_command",
                    command=short_id(kind),
                )
                await emit(
                    {
                        "type": "command_result",
                        "request_id": raw["request_id"],
                        "command": kind or "unknown",
                        "success": False,
                        "message": "unknown_command",
                    }
                )

    except WebSocketDisconnect:
        log_event(logger, logging.INFO, "disconnect")
    except Exception as exc:
        log_event(
            logger,
            logging.ERROR,
            "handler_error",
            error=type(exc).__name__,
        )
        await emit({"type": "error", "message": str(exc)})
    finally:
        log_event(logger, logging.INFO, "connection_closing")
        if prompt_task and not prompt_task.done():
            prompt_task.cancel()
        with contextlib.suppress(Exception):
            await adapter.close()
        log_event(logger, logging.INFO, "adapter_cleanup")
        # Mark the persisted session inactive on disconnect.
        repo = getattr(websocket.app.state, "history_repository", None)
        if repo is not None:
            with contextlib.suppress(Exception):
                repo.set_status(rtai_session_id, SessionStatus.INACTIVE)
        # Clean up the temporary session directory if we created one.
        if session_dir is not None:
            import shutil

            shutil.rmtree(session_dir, ignore_errors=True)


# Explicitly reserved API prefix — any path under /api that hits here but has
# no matching handler returns a JSON 404, never the SPA HTML fallback.
@router.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def _api_catch_all(path: str) -> dict[str, Any]:
    raise HTTPException(
        status_code=404,
        detail={"error": "api_route_not_found", "path": f"/api/{path}"},
    )
