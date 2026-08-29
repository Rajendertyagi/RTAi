"""Protocol v1 WebSocket and HTTP routes.

Each incoming WebSocket gets its own adapter instance, its own sequence
counters, and its own permission tracker.  Cleanup always targets only
the handle this connection created — never another caller's process.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect

from ..agents.base import AgentAdapter
from ..core.protocol import resolve_project_path
from ..logging_config import log_event, short_id
from .protocol_v1 import (
    PROTOCOL_VERSION,
    normalize_emission,
    snapshot_to_v1_events,
    validate_command,
)

router = APIRouter()

logger = logging.getLogger(__name__)


@router.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.websocket("/ws")
async def chat_socket(websocket: WebSocket, cwd: str | None = Query(default=None)) -> None:
    await websocket.accept()
    log_event(logger, logging.INFO, "ws_accepted", cwd=cwd or "not_provided")
    send_lock = asyncio.Lock()

    # Correlation aliases for the active turn; updated by the prompt branch.
    turn_ctx: dict[str, str] = {}
    # Monotonic per-turn sequence counter for streaming deltas.
    delta_seq = 0

    async def emit(raw: dict[str, Any]) -> None:
        """Send a Protocol v1 frame with the authoritative envelope.

        ``protocol_version`` is injected here so every outbound frame carries
        the v1 marker the frontend requires.  The field is set after the raw
        payload is copied so adapter-provided values cannot override it.
        """
        session_id = turn_ctx.get("session_id", "")
        if session_id:
            # Wrap with the authoritative envelope (session_id, turn_id,
            # timestamp, and a per-turn sequence for deltas) so streaming
            # events carry the correlation fields the frontend requires.
            nonlocal delta_seq
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

    # Validate project path early so we can reject before creating the adapter.
    project: Path | None = None
    try:
        project = resolve_project_path(cwd)
    except ValueError as exc:
        if str(exc) == "project_folder_not_provided":
            log_event(logger, logging.INFO, "project_folder_missing")
            # No cwd supplied and no RTAI_PROJECT_ROOT configured — keep the
            # WebSocket open so the UI can prompt the user for a folder.
            await emit({
                "type": "error",
                "message": (
                    "No project folder specified. Enter a valid folder path "
                    "in the control bar, or set RTAI_PROJECT_ROOT."
                ),
                "code": "project_folder_not_provided",
            })
            # Stay in a holding loop until the client disconnects.
            while True:
                raw = await websocket.receive_json()
                if not isinstance(raw, dict):
                    continue
                kind = raw.get("type")
                if kind == "prompt":
                    await emit({
                        "type": "command_result",
                        "request_id": raw.get("request_id"),
                        "command": "prompt",
                        "success": False,
                        "message": "project_folder_not_provided",
                    })
                elif kind in ("cancel", "select_agent", "select_model", "select_mode",
                              "set_thinking", "permission_response"):
                    await emit({
                        "type": "command_result",
                        "request_id": raw.get("request_id"),
                        "command": kind,
                        "success": False,
                        "message": "project_folder_not_provided",
                    })
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
        await emit({"type": "status", "state": "starting", "cwd": str(project)})
        await adapter.start(project, emit)
        log_event(logger, logging.INFO, "adapter_started")

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
                    await emit({
                        "type": "command_result",
                        "request_id": raw.get("request_id"),
                        "command": "prompt",
                        "success": False,
                        "message": err,
                    })
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
                    await emit({
                        "type": "command_result",
                        "request_id": raw.get("request_id"),
                        "command": "prompt",
                        "success": False,
                        "message": "A response is already running",
                    })
                    continue
                session_id: str = raw["session_id"]
                turn_id: str = raw["turn_id"]
                msg_id: str = raw["message_id"]
                text: str = raw["text"]
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
                    text_length=len(text),
                )

                async def _turn(
                    _text: str = text,
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
                        await emit({
                            "type": "done",
                            "session_id": _session_id,
                            "turn_id": _turn_id,
                            "reason": "cancelled",
                        })
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
                        await emit({
                            "type": "error",
                            "session_id": _session_id,
                            "turn_id": _turn_id,
                            "message": str(exc),
                        })

                prompt_task = asyncio.create_task(_turn())
                # Emit user_message so the UI binds the response window.
                await emit({
                    "type": "user_message",
                    "session_id": session_id,
                    "turn_id": turn_id,
                    "message_id": msg_id,
                    "text": text,
                })
                await emit({
                    "type": "command_result",
                    "request_id": raw["request_id"],
                    "command": "prompt",
                    "success": True,
                })
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
                    await emit({
                        "type": "command_result",
                        "request_id": raw.get("request_id"),
                        "command": "cancel",
                        "success": False,
                        "message": err,
                    })
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
                await emit({
                    "type": "command_result",
                    "request_id": raw["request_id"],
                    "command": "cancel",
                    "success": True,
                })
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
                    await emit({
                        "type": "command_result",
                        "request_id": raw.get("request_id"),
                        "command": kind,
                        "success": False,
                        "message": err,
                    })
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
                await emit({
                    "type": "command_result",
                    "request_id": raw["request_id"],
                    "command": kind,
                    "success": result.applied,
                    "message": result.message,
                })
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
                    await emit({
                        "type": "command_result",
                        "request_id": raw.get("request_id"),
                        "command": "permission_response",
                        "success": False,
                        "message": err,
                    })
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
                await emit({
                    "type": "permission_result",
                    "session_id": raw["session_id"],
                    "turn_id": raw["turn_id"],
                    "permission_request_id": pid,
                    "option_id": option_id,
                })
                await emit({
                    "type": "command_result",
                    "request_id": raw["request_id"],
                    "command": "permission_response",
                    "success": resolved,
                })
                continue

            # Unknown command — acknowledge failure if request_id present.
            if raw.get("request_id"):
                log_event(
                    logger,
                    logging.INFO,
                    "malformed_command",
                    command=short_id(kind),
                )
                await emit({
                    "type": "command_result",
                    "request_id": raw["request_id"],
                    "command": kind or "unknown",
                    "success": False,
                    "message": "unknown_command",
                })

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


# Explicitly reserved API prefix — any path under /api that hits here but has
# no matching handler returns a JSON 404, never the SPA HTML fallback.
@router.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def _api_catch_all(path: str) -> dict[str, Any]:
    raise HTTPException(
        status_code=404,
        detail={"error": "api_route_not_found", "path": f"/api/{path}"},
    )
