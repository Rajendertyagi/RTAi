"""POST /assistant — official ``assistant-stream`` transport.

Uses ``create_run`` + ``RunController`` and returns
``DataStreamResponse``.  The request shape follows the official
AssistantTransport contract: ``state, commands, system, tools, threadId,
parentId, callSettings, config``.  No custom envelope is invented.

Official source:
https://www.assistant-ui.com/docs/runtimes/custom/assistant-transport
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

# PyPI Python package (backend dependency: assistant-stream==0.0.36), NOT the
# separate npm assistant-stream@^0.3.40 pulled by @assistant-ui/react on the frontend.
from assistant_stream import RunController, create_run
from assistant_stream.serialization import DataStreamResponse
from fastapi import APIRouter, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ...agents.prompt_content import (
    PromptValidationError,
    parse_inline_data_url,
    submit_prompt_blocks,
)
from ...logging_config import log_event, short_id
from .acp_state_projector import (
    _EXPIRED_REASON,
    AcpStateProjector,
    _ensure_assistant_message,
    _set_status,
    project_capabilities,
    set_capability_error,
)
from .models import (
    RTAI_REFRESH_COMMAND,
    RTAI_SELECT_COMMANDS,
    AssistantTransportRequest,
    ensure_state_shape,
    prepare_validated_commands,
)
from .session_manager import (
    close_session,
    get_entry,
    get_entry_any,
    get_or_create_adapter,
    touch_session,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/assistant")
async def assistant_transport(request: Request) -> DataStreamResponse:
    """Handle an AssistantTransport POST.

    Only ``type == "add-message"`` commands with the official shape
    ``{type, message:{role, parts}, parentId, sourceId}`` are processed.
    """
    body: dict[str, Any] = {}
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}

    try:
        parsed = AssistantTransportRequest.model_validate(body)
    except Exception:
        parsed = AssistantTransportRequest(
            state=body.get("state"),
            commands=body.get("commands") if isinstance(body.get("commands"), list) else [],
            system=body.get("system"),
            tools=body.get("tools"),
            threadId=body.get("threadId"),
            parentId=body.get("parentId"),
            callSettings=body.get("callSettings"),
            config=body.get("config"),
        )

    # Session identity: state.sessionId → threadId → new UUID (no "default" fallback)
    initial_state, session_key, _is_new = ensure_state_shape(
        parsed.state, thread_id=parsed.threadId
    )

    # === Pre-stream validation (before DataStreamResponse) ===
    # Simulate commands against a temporary message list to validate parentId,
    # generate stable IDs, and ensure request can return HTTP 400 instead of
    # streaming an error.  This is the sole validation site; the run callback
    # applies only already-validated commands and never raises HTTPException.
    # Also check for closing session to return honest pre-stream 409 instead of
    # spawning another process.
    raw_commands = parsed.commands if isinstance(parsed.commands, list) else []
    try:
        prepared_commands = prepare_validated_commands(
            initial_state.get("messages", []),  # type: ignore[arg-type]
            raw_commands,
        )
    except RequestValidationError:
        # Schema-level violations of custom capability commands (missing/blank/
        # oversized/alias/extra fields) surface as FastAPI's standard 422.
        raise
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail={"error": "invalid_request", "reason": str(exc)}
        ) from None

    # Prevent creating a replacement adapter while previous is still closing
    try:
        from .session_manager import get_entry_any

        entry_any = get_entry_any(session_key)
        if entry_any is not None and entry_any.state in ("closing", "close_failed"):
            raise HTTPException(
                status_code=409, detail={"error": "session_closing", "sessionId": session_key}
            )
    except HTTPException:
        raise
    except Exception:
        pass

    log_event(
        logger,
        logging.INFO,
        "assistant_request_received",
        session=short_id(session_key),
        has_commands=bool(prepared_commands),
    )

    factory = getattr(request.app.state, "adapter_factory", None)
    if factory is None:
        from ...agents.factory import create_default_factory

        factory = create_default_factory()

    async def run(controller: RunController) -> None:
        # Seed controller.state from initial_state (create_run already does this,
        # but ensure the proxy reflects the generated sessionId).
        try:
            if controller.state is None:
                controller.state = initial_state  # type: ignore[assignment]
            else:
                # Reconcile if client sent different snapshot (should not happen after generation)
                try:
                    existing_sid = controller.state["sessionId"]  # type: ignore[index]
                    if existing_sid != session_key:
                        controller.state["sessionId"] = session_key  # type: ignore[index]
                except Exception:
                    controller.state["sessionId"] = session_key  # type: ignore[index]
        except Exception:
            pass

        if not prepared_commands:
            _set_status(controller, "ready")
            controller.flush()
            return

        # Command-order policy (enforced in prepare_validated_commands before
        # streaming): capability-only and add-message-only batches are allowed; zero
        # or more capability commands followed by one or more add-message commands are
        # allowed (capability changes affect this prompt); any capability command
        # after the first add-message is rejected with HTTP 400 unsupported_command_order.
        # The single in-order pass below applies each command exactly once, in order.
        # One long-lived adapter + per-session turn lock serialize the whole batch
        # (no race with an active run). get_or_create_adapter performs per-session
        # SINGLE-FLIGHT creation: it does NOT hold the registry lock during
        # adapter.start(), so a slow OpenCode startup on one session never blocks
        # creation or requests for another.
        adapter = await get_or_create_adapter(
            session_key,
            factory=factory,
            state=initial_state,
            config=parsed.config,
        )
        # Update idle activity when the entry is obtained for a request
        touch_session(session_key)
        entry = get_entry(session_key)
        if entry is not None:
            await entry.lock.acquire()
            # Update activity when turn starts
            touch_session(session_key)

        try:
            projector = AcpStateProjector(controller, session_key=session_key)
            prompt_task: asyncio.Task[None] | None = None
            cancel_task: asyncio.Task[bool] | None = None
            cancelled = False

            # Single in-order pass over the prepared command list. The command order is
            # already enforced upstream in prepare_validated_commands: any capability
            # command appearing after the first add-message was rejected with HTTP 400
            # unsupported_command_order before streaming, so here capability commands
            # always precede add-message commands and take effect on this prompt. The
            # list is processed exactly once, in order — never reordered, deferred,
            # duplicated, or dropped. A capability-only batch is finalized as ready
            # after projecting the authoritative snapshot.
            raw_blocks: list[dict[str, Any]] = []
            has_add_message = False
            for cmd in prepared_commands:
                if not isinstance(cmd, dict):
                    continue
                ctype = str(cmd.get("type", ""))
                if ctype == "add-message":
                    has_add_message = True
                    message = cmd["message"]  # validated, stable id already present
                    parent_id = cmd.get("parentId")
                    if isinstance(parent_id, str) and parent_id:
                        # Truncate after parent (validated to exist in simulation)
                        try:
                            messages_proxy = controller.state["messages"]  # type: ignore[index]
                            parent_idx: int | None = None
                            n = len(messages_proxy)  # type: ignore[arg-type]
                            for i in range(n):  # type: ignore[arg-type]
                                try:
                                    m = messages_proxy[i]  # type: ignore[index]
                                    # controller.state["messages"][i] is a StateProxy
                                    # element, not a plain dict, so isinstance(m, dict)
                                    # is False and would force mid=None. Read id via .get,
                                    # which works for both plain dicts and StateProxy views.
                                    mid = m.get("id") if hasattr(m, "get") else None
                                    if isinstance(mid, str) and mid == parent_id:
                                        parent_idx = i
                                        break
                                except Exception:
                                    continue
                            if parent_idx is None:
                                # Should not happen after pre-validation; treat as stream error.
                                _set_status(controller, "error", error="parent_not_found")
                                with contextlib.suppress(Exception):
                                    controller.add_error("parent_not_found")
                                controller.flush()
                                return
                            truncated: list[Any] = []
                            for i in range(parent_idx + 1):  # type: ignore[arg-type]
                                with contextlib.suppress(Exception):
                                    truncated.append(initial_state["messages"][i])  # type: ignore[index]
                            controller.state["messages"] = truncated  # type: ignore[index]
                        except Exception:
                            _set_status(controller, "error", error="parent_truncate_failed")
                            with contextlib.suppress(Exception):
                                controller.add_error("parent_truncate_failed")
                            controller.flush()
                            return
                    try:
                        controller.state["messages"].append(message)  # type: ignore[attr-defined,index]
                    except Exception:
                        try:
                            msgs = controller.state["messages"]  # type: ignore[index]
                            msgs.append(message)  # type: ignore[attr-defined]
                        except Exception:
                            pass
                    parts = message.get("parts") if isinstance(message, dict) else None
                    if isinstance(parts, list):
                        for part in parts:
                            if not isinstance(part, dict):
                                continue
                            ptype = part.get("type")
                            if ptype == "text":
                                t = part.get("text")
                                if isinstance(t, str) and t:
                                    raw_blocks.append(
                                        {"kind": "text", "name": "message", "text": t}
                                    )
                            elif ptype == "image":
                                data_url = part.get("image")
                                if isinstance(data_url, str) and data_url.startswith("data:"):
                                    # Shared strict parser: enforces the exact
                                    # data:<mime>;base64,<payload> grammar, the
                                    # explicit image MIME allowlist, and strict
                                    # base64. Pre-stream validation already rejects
                                    # malformed parts with HTTP 400, so this is a
                                    # defensive guard only.
                                    try:
                                        mime, b64 = parse_inline_data_url(data_url)
                                    except PromptValidationError:
                                        continue
                                    name = part.get("filename") or "image"
                                    raw_blocks.append(
                                        {
                                            "kind": "image",
                                            "name": name,
                                            "mime_type": mime,
                                            "data_base64": b64,
                                        }
                                    )
                elif ctype.startswith("rtai."):
                    # Authoritative, sequential, no optimistic claim. Applied before the
                    # prompt so selection/refresh affects this turn.
                    await _apply_capability_command(controller, adapter, cmd, session_key)

            if not has_add_message or not raw_blocks:
                # Capability-only batch (or empty message): finalize ready with the
                # projected capability state already written to controller.state.
                _set_status(controller, "ready")
                controller.flush()
                return

            _ensure_assistant_message(controller)
            _set_status(controller, "running")
            controller.flush()

            # Bind projector to the stable dispatch while holding the lock (prompt path only)
            if entry is not None:
                entry.dispatch.bind(projector)

            try:
                log_event(
                    logger,
                    logging.DEBUG,
                    "assistant_prompt_entered",
                    session=short_id(session_key),
                )

                async def _do_prompt() -> None:
                    await submit_prompt_blocks(adapter, raw_blocks)

                prompt_task = asyncio.create_task(_do_prompt())
                cancel_task = asyncio.create_task(controller.cancelled_event.wait())

                done, pending = await asyncio.wait(
                    {prompt_task, cancel_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )

                if prompt_task in done:
                    # Prompt finished first — consume result normally
                    cancel_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await cancel_task
                    try:
                        prompt_task.result()
                    except asyncio.CancelledError:
                        cancelled = True
                        _set_status(controller, "cancelled")
                    except Exception as exc:
                        _set_status(controller, "error", error=type(exc).__name__)
                        with contextlib.suppress(Exception):
                            controller.add_error(type(exc).__name__)
                        log_event(
                            logger,
                            logging.ERROR,
                            "assistant_prompt_failed",
                            session=short_id(session_key),
                            error=type(exc).__name__,
                        )
                    else:
                        if not cancelled and not controller.is_cancelled:
                            try:
                                if (
                                    controller.state is not None
                                    and controller.state["status"] == "running"
                                ):  # type: ignore[index]
                                    _set_status(controller, "complete")
                            except Exception:
                                _set_status(controller, "complete")
                        log_event(
                            logger,
                            logging.DEBUG,
                            "assistant_prompt_returned",
                            session=short_id(session_key),
                        )
                else:
                    # Cancellation finished first
                    cancelled = True
                    log_event(
                        logger,
                        logging.INFO,
                        "assistant_cancel_observed",
                        session=short_id(session_key),
                    )
                    try:
                        await adapter.cancel()
                    except Exception:
                        log_event(logger, logging.WARNING, "assistant_cancel_failed")
                    prompt_task.cancel()
                    try:
                        await prompt_task
                    except asyncio.CancelledError:
                        pass
                    except Exception as exc:
                        _set_status(controller, "error", error=type(exc).__name__)
                    _set_status(controller, "cancelled")
                    # Ensure cancel_task is done
                    cancel_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await cancel_task

                controller.flush()
            except asyncio.CancelledError:
                # Run callback itself was cancelled (client disconnect)
                cancelled = True
                with contextlib.suppress(Exception):
                    await adapter.cancel()
                _set_status(controller, "cancelled")
                controller.flush()
                raise
        finally:
            # Update activity when turn finishes
            with contextlib.suppress(Exception):
                touch_session(session_key)
            if entry is not None:
                # Serialize turn cleanup with in-flight permission responses via the
                # dedicated permission lock. The turn lock (entry.lock) is already
                # held here and is released AFTER the permission lock, preserving the
                # required order: entry.lock first, then permission_lock (reverse on release).
                async with entry.permission_lock:
                    entry.dispatch.unbind(projector)
                    # Drop permission metadata for this turn; the resolved approval
                    # state already lives in controller.state (streamed to the UI).
                    entry.dispatch.clear_permissions()
                entry.lock.release()
            # Always cancel/await the temporary cancel_task
            if cancel_task is not None and not cancel_task.done():
                cancel_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await cancel_task
            if prompt_task is not None and not prompt_task.done():
                prompt_task.cancel()
                try:
                    await prompt_task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass
            log_event(
                logger,
                logging.DEBUG,
                "assistant_turn_finalized",
                session=short_id(session_key),
                cancelled=cancelled,
            )

    return DataStreamResponse(create_run(run, state=initial_state))


@router.delete("/assistant/sessions/{session_id}")
async def delete_assistant_session(session_id: str) -> Response:
    """Application session lifecycle: close the backend AssistantTransport session.

    Idempotent: returns 204 when closed or already absent. Does not expose
    adapter/process internals. Not a streaming protocol.
    """
    # Decode is handled by FastAPI path param; ensure non-empty
    if not session_id or not session_id.strip():
        return Response(status_code=204)
    sid = session_id.strip()
    try:
        await close_session(sid)
    except Exception as exc:
        # Honest 5xx on failure; log only short id, class and lifecycle stage
        log_event(
            logger,
            logging.ERROR,
            "assistant_session_close_failed",
            session=short_id(sid),
            error=type(exc).__name__,
        )
        raise HTTPException(status_code=500, detail={"error": "close_failed"}) from None
    return Response(status_code=204)


async def _apply_capability_command(
    controller: RunController,
    adapter: Any,
    cmd: dict[str, Any],
    session_key: str,
) -> None:
    """Apply one validated RTAI capability custom command authoritatively.

    Uses only the adapter's public ``capability_snapshot()`` / ``select()``
    contract. A successful selection refreshes and projects the authoritative
    server snapshot (never an optimistic claim). An adapter rejection preserves
    the prior server-selected value and exposes a safe transport error that does
    not leak the submitted payload.
    """
    ctype = cmd.get("type")
    if ctype == RTAI_REFRESH_COMMAND:
        project_capabilities(controller, adapter.capability_snapshot())
        return
    kind = RTAI_SELECT_COMMANDS.get(ctype)
    if kind is None:
        return
    value = cmd.get("value")
    try:
        result = await adapter.select(kind, value)
    except Exception as exc:
        log_event(
            logger,
            logging.WARNING,
            "assistant_capability_select_failed",
            session=short_id(session_key),
            kind=kind,
            error=type(exc).__name__,
        )
        set_capability_error(controller, kind, "Selection could not be applied.")
        return
    if result.applied:
        project_capabilities(controller, adapter.capability_snapshot())
    else:
        # Preserve prior server-selected value; expose a safe, payload-free error.
        set_capability_error(controller, kind, "Selection could not be applied.")


class PermissionResponseRequest(BaseModel):
    """Strict body for the permission-response endpoint.

    Only ``optionId`` (non-empty, bounded) is accepted; aliases (option_id,
    option, choice, result) and extra fields are rejected. ACP option IDs are
    exact, so the original value is returned unchanged (never trimmed or
    normalized). FastAPI validates this model and returns **422** for
    malformed/blank/oversized/alias/extra-field bodies; a well-formed
    ``optionId`` that is not one of the permission's registered options is
    rejected by the handler with **400**.
    """

    model_config = ConfigDict(extra="forbid")
    optionId: str = Field(min_length=1, max_length=256)

    @field_validator("optionId")
    @classmethod
    def _check_not_blank(cls, value: str) -> str:
        # Reject whitespace-only without altering valid IDs; return the original
        # value byte-for-byte so ACP option IDs remain unchanged.
        if value.strip() == "":
            raise ValueError("optionId must not be blank")
        return value


@router.post("/assistant/sessions/{session_id}/permissions/{permission_id}")
async def respond_assistant_permission(
    session_id: str,
    permission_id: str,
    payload: PermissionResponseRequest,
) -> Response:
    """Resolve a pending ACP permission while the original AssistantTransport stream stays open.

    This endpoint does NOT acquire the per-turn lock (the active prompt owns it
    while blocked on the ACP permission future). It calls the adapter's public
    ``respond_to_permission`` concurrently to unblock the future, then records and
    projects the resolution. It never routes through the AssistantTransport command queue.

    Request validation is delegated to ``PermissionResponseRequest``: FastAPI
    returns **422** for malformed/blank/oversized/alias/extra-field bodies, and
    this handler returns **400** only when a well-formed ``optionId`` is not one
    of the permission's registered options.
    """
    if not session_id or not session_id.strip():
        raise HTTPException(status_code=400, detail={"error": "invalid_session_id"})
    sid = session_id.strip()
    if not permission_id or not permission_id.strip():
        raise HTTPException(status_code=400, detail={"error": "invalid_permission_id"})
    pid = permission_id.strip()

    # The body is already validated by FastAPI (422 on failure). Use the original,
    # untrimmed value so ACP option IDs are compared byte-for-byte.
    option_id = payload.optionId

    # Read-only session lookup; do NOT acquire the per-turn lock.
    entry = get_entry_any(sid)
    if entry is None:
        raise HTTPException(status_code=404, detail={"error": "unknown_session"})
    if entry.state in ("closing", "closed", "close_failed"):
        raise HTTPException(status_code=409, detail={"error": "session_closing"})

    # Permission-resolution critical section. The dedicated permission lock
    # serializes this sequence against the run() finally cleanup (which acquires
    # the same lock before unbinding the projector and clearing permissions) so an
    # accepted resolution is always recorded and projected before turn cleanup can
    # erase it. The turn lock is NOT acquired here (it is owned by the active
    # prompt) so there is no deadlock with the in-flight permission response.
    async with entry.permission_lock:
        perm = entry.dispatch.permissions.get(pid)
        if perm is None:
            raise HTTPException(status_code=404, detail={"error": "unknown_permission"})

        # Already expired/inactive: never retryable.
        if perm.resolution == "expired":
            raise HTTPException(status_code=409, detail={"error": "permission_not_active"})

        # Already resolved: identical retry → 204; different option → 409.
        if perm.resolution == "resolved":
            if perm.selected_option_id == option_id:
                return Response(status_code=204)
            raise HTTPException(status_code=409, detail={"error": "permission_already_resolved"})

        # Unsupported: no selectable options. No optionId can be submitted.
        if not perm.option_kinds:
            raise HTTPException(status_code=409, detail={"error": "unsupported_permission_options"})

        if option_id not in perm.option_kinds:
            raise HTTPException(status_code=400, detail={"error": "invalid_option"})

        # Resolve the ACP pending future concurrently (no turn lock held here).
        try:
            ok = await entry.adapter.respond_to_permission(pid, option_id)
        except Exception as exc:
            log_event(
                logger,
                logging.ERROR,
                "assistant_permission_adapter_failed",
                session=short_id(sid),
                permission=short_id(pid),
                error=type(exc).__name__,
            )
            raise HTTPException(
                status_code=500, detail={"error": "permission_response_failed"}
            ) from None

        # False: future missing/completed/inactive. Mark expired (not retryable)
        # and project the terminal approval state; never ask the frontend to retry.
        if not ok:
            entry.dispatch.permissions.mark_expired(pid)
            entry.dispatch.set_approval_expired(pid, _EXPIRED_REASON)
            log_event(
                logger,
                logging.WARNING,
                "assistant_permission_not_active",
                session=short_id(sid),
                permission=short_id(pid),
            )
            raise HTTPException(status_code=409, detail={"error": "permission_not_active"})

        # ACP accepted the option. Record the resolution in the session registry.
        entry.dispatch.permissions.resolve(pid, option_id)
        kind = perm.option_kinds.get(option_id, "")
        approved = kind in ("allow-once", "allow-always")
        # Project only if the projector is still bound; otherwise the next ACP
        # event (tool_result/done) re-synchronizes the stored resolution.
        applied = entry.dispatch.set_approval_resolved(pid, option_id, approved)
        if not applied:
            log_event(
                logger,
                logging.WARNING,
                "assistant_permission_state_deferred",
                session=short_id(sid),
                permission=short_id(pid),
            )
        # 204: ACP already accepted; never ask the frontend to retry an accepted option.
        return Response(status_code=204)
