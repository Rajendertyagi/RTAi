from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import shutil
from pathlib import Path
from typing import Any

from ..core.protocol import jsonable_model, text_from_acp_update
from ..logging_config import log_event, short_id
from .base import AgentAdapter, Emit, SelectionKind, SelectionResult
from .capabilities import (
    AgentDescriptor,
    CapabilitySection,
    CapabilitySnapshot,
    UnavailabilityReason,
    UnavailableCapability,
)
from .opencode.capability_mapper import AcpCapabilityState, command_item
from .owned_process import OwnedProcess

logger = logging.getLogger(__name__)

_PHASE_MESSAGE = "Runtime capability discovery arrives in Phase 2A-B."


def _pending_section() -> CapabilitySection[Any]:
    return CapabilitySection(
        items=(),
        unavailable=UnavailableCapability(UnavailabilityReason.PENDING_DISCOVERY, _PHASE_MESSAGE),
    )


def _permission_option(option: Any, index: int) -> dict[str, str]:
    """Map an ACP PermissionOption (pydantic model or dict) to a Protocol v1 item.

    The ACP SDK hands ``request_permission`` a list of pydantic
    ``PermissionOption`` models (``optionId``/``name``/``kind``), not dicts.
    ``kind`` is included when present so the UI can auto-pick allow options.
    """
    if isinstance(option, dict):
        option_id = option.get("optionId", option.get("id", index))
        label = option.get("name", option.get("label", f"Option {index}"))
        kind = option.get("kind", "")
    else:
        option_id = getattr(option, "optionId", index)
        label = getattr(option, "name", f"Option {index}")
        kind = getattr(option, "kind", "")
    item: dict[str, str] = {"id": str(option_id), "label": str(label)}
    if kind:
        item["kind"] = str(kind)
    return item


class OpenCodeSession(AgentAdapter):
    """Adapter around the official ACP Python SDK for one OpenCode child.

    The child process spawned here is the ONLY OpenCode process this class
    ever touches; its handle is retained in an :class:`OwnedProcess` so
    cleanup stays scoped to what RTAi created (ADR-0006).
    """

    def __init__(self) -> None:
        self._context: Any = None
        self._connection: Any = None
        self._session_id: str | None = None
        self._emit: Emit | None = None
        self._owned: OwnedProcess | None = None
        self._agent_name: str | None = None
        self._agent_title: str | None = None
        self._agent_version: str | None = None
        self._initialized = False
        self._capabilities = AcpCapabilityState()
        self._load_session_cap: bool | None = None
        self._pending_permissions: dict[str, Any] = {}

    async def start(self, cwd: Path, emit: Emit) -> None:
        try:
            from acp import PROTOCOL_VERSION, spawn_agent_process
            from acp.interfaces import Client
        except ImportError as exc:
            raise RuntimeError(
                "ACP SDK is missing. Run: pip install -r requirements.txt"
            ) from exc

        executable = os.environ.get("OPENCODE_BIN") or shutil.which("opencode")
        if not executable:
            raise RuntimeError("OpenCode was not found in PATH (expected 'opencode')")

        log_event(
            logger,
            logging.INFO,
            "acp_spawn_requested",
            executable=Path(executable).name,
            **({"executable_path": executable} if logger.isEnabledFor(logging.DEBUG) else {}),
        )

        self._emit = emit
        owner = self

        class BrowserClient(Client):
            _perm_counter = 0

            async def request_permission(
                self, session_id: str, tool_call: Any, options: list[Any], **kwargs: Any
            ) -> Any:
                BrowserClient._perm_counter += 1
                perm_id = f"perm-{BrowserClient._perm_counter}"
                fut = asyncio.get_event_loop().create_future()
                owner._pending_permissions[perm_id] = fut

                await owner._send(
                    {
                        "type": "permission_request",
                        "permission_request_id": perm_id,
                        "tool_call_id": str(
                            getattr(
                                tool_call,
                                "id",
                                getattr(
                                    tool_call,
                                    "tool_call_id",
                                    f"tc-{perm_id}",
                                ),
                            )
                        ),
                        "options": [
                            _permission_option(o, i)
                            for i, o in enumerate(options)
                        ],
                    }
                )
                log_event(
                    logger,
                    logging.INFO,
                    "acp_permission_request",
                    permission=short_id(perm_id),
                )
                try:
                    option_id = await asyncio.wait_for(fut, timeout=300.0)
                    # ACP RequestPermissionResponse is a discriminated union:
                    # selected + optionId, or cancelled. Anything else fails
                    # pydantic validation on the agent side and reads as reject.
                    return {"outcome": {"outcome": "selected", "optionId": option_id}}
                except asyncio.TimeoutError:
                    return {"outcome": {"outcome": "cancelled"}}
                finally:
                    owner._pending_permissions.pop(perm_id, None)

            async def session_update(
                self, session_id: str, update: Any, **kwargs: Any
            ) -> None:
                log_event(
                    logger,
                    logging.DEBUG,
                    "acp_session_update",
                    event_type=type(update).__name__,
                )
                dumped = jsonable_model(update)
                await owner._send(
                    {
                        "type": "raw",
                        "event": type(update).__name__,
                        "data": dumped,
                    }
                )
                text = text_from_acp_update(update)
                if text:
                    await owner._send({"type": "delta", "text": text})
                owner._ingest_notification(dumped)
                if dumped.get("sessionUpdate") == "available_commands_update":
                    await owner._emit_commands_available()

        # Runtime note: Client has no __abstractmethods__ on the pinned SDK,
        # so partial implementations work. mypy still treats empty bodies as
        # implicitly abstract, hence the narrow ignore below.
        self._context = spawn_agent_process(
            BrowserClient(),  # type: ignore[abstract]
            executable,
            "acp",
            env=os.environ.copy(),
        )
        self._connection, process = await self._context.__aenter__()
        argv = [executable, "acp"]
        self._owned = OwnedProcess(
            handle=process,
            pid=getattr(process, "pid", None),
            argv=argv,
            cooperative_close=self._close_context,
        )
        log_event(
            logger,
            logging.INFO,
            "acp_child_started",
            pid=self._owned.pid,
        )
        try:
            init_response = await self._connection.initialize(
                protocol_version=PROTOCOL_VERSION
            )
            self._capture_agent_identity(init_response)
            session = await self._connection.new_session(cwd=str(cwd), mcp_servers=[])
            self._session_id = session.session_id
            self._initialized = True
            self._owned.attach_session(self._session_id or "")
            log_event(
                logger,
                logging.INFO,
                "acp_session_created",
                session=short_id(self._session_id),
            )
            log_event(logger, logging.INFO, "acp_initialized")
            self._capabilities.ingest_session_state(jsonable_model(session))
            load_cap = getattr(init_response, "loadSession", None)
            self._load_session_cap = bool(load_cap) if load_cap is not None else None
        except BaseException:
            # Startup failed after spawn: clean up exactly what we created and
            # drop the wrapper - there is no owned child left to expose.
            self._initialized = False
            await self._close_context()
            if self._owned is not None:
                self._owned.mark_start_failed()
            self._owned = None
            raise

    async def submit_prompt(self, text: str) -> None:
        if not self._connection or not self._session_id:
            raise RuntimeError("ACP session is not ready")
        from acp import text_block

        log_event(
            logger,
            logging.DEBUG,
            "acp_prompt_submitted",
            session=short_id(self._session_id),
            text_length=len(text),
        )
        await self._connection.prompt(
            session_id=self._session_id,
            prompt=[text_block(text)],
        )
        log_event(
            logger,
            logging.DEBUG,
            "acp_turn_completed",
            session=short_id(self._session_id),
        )
        await self._send({"type": "done"})

    async def cancel(self) -> None:
        if self._connection and self._session_id:
            log_event(
                logger,
                logging.DEBUG,
                "acp_cancel_requested",
                session=short_id(self._session_id),
            )
            await self._connection.cancel(session_id=self._session_id)

    async def close(self) -> None:
        # Resolve all pending permissions as cancelled before tearing down.
        for fut in self._pending_permissions.values():
            if not fut.done():
                fut.cancel()
        if self._pending_permissions:
            log_event(
                logger,
                logging.DEBUG,
                "acp_permission_cleanup",
                count=len(self._pending_permissions),
            )
        self._pending_permissions.clear()
        if self._owned is not None:
            await self._owned.close()
        elif self._context is not None:
            await self._close_context()
        self._context = self._connection = self._session_id = None
        self._owned = None
        self._initialized = False

    def owned_process(self) -> OwnedProcess | None:
        return self._owned

    async def respond_to_permission(self, permission_request_id: str, option_id: str) -> bool:
        """Resolve a pending permission request with the user's choice.

        Returns True if the request was found and resolved; False otherwise.
        """
        fut = self._pending_permissions.pop(permission_request_id, None)
        if fut is None or fut.done():
            return False
        if not fut.cancelled():
            fut.set_result(option_id)
        log_event(
            logger,
            logging.DEBUG,
            "acp_permission_resolved",
            permission=short_id(permission_request_id),
        )
        return True

    def capability_snapshot(self) -> CapabilitySnapshot:
        if not self._initialized:
            agent: AgentDescriptor | UnavailableCapability = UnavailableCapability(
                UnavailabilityReason.PENDING_DISCOVERY,
                "Agent identity becomes available after initialization.",
            )
        else:
            name = self._agent_name or "opencode"
            # ACP exposes exactly one agent identity (agentInfo). `name` is the
            # programmatic id; `title` is the display label when provided.
            agent = AgentDescriptor(id=name.lower(), label=self._agent_title or name)
        if not self._initialized:
            return CapabilitySnapshot(
                source=f"acp:{(self._agent_name or 'opencode').lower()}",
                agent=agent,
                models=_pending_section(),
                modes=_pending_section(),
                thinking_options=_pending_section(),
                commands=_pending_section(),
            )
        caps = self._capabilities
        # OpenCode exposes its agents (build, plan, and locally configured
        # profiles) through ACP as session modes, so the agents section mirrors
        # the modes. The single agentInfo identity stays on snapshot.agent and
        # is surfaced separately (agent_info event / status bar).
        agents = CapabilitySection(
            items=tuple(
                AgentDescriptor(id=m.id, label=m.label, description=m.description)
                for m in caps.modes.items
            )
        )
        if caps.selected_mode is not None:
            caps.selected_agent = caps.selected_mode
        return CapabilitySnapshot(
            source=f"acp:{(self._agent_name or 'opencode').lower()}",
            agent=agent,
            agents=agents,
            models=caps.models,
            modes=caps.modes,
            thinking_options=caps.thinking,
            commands=caps.commands,
            attachments=UnavailableCapability(
                UnavailabilityReason.PENDING_DISCOVERY,
                "Attachment support is negotiated during initialization.",
            ),
            sessions=UnavailableCapability(
                UnavailabilityReason.PENDING_DISCOVERY,
                "Session feature flags arrive with the initialize response.",
            ),
        )

    async def _close_context(self) -> None:
        if self._context is not None:
            with contextlib.suppress(Exception):
                await self._context.__aexit__(None, None, None)

    def _capture_agent_identity(self, init_response: Any) -> None:
        info = getattr(init_response, "agentInfo", None)
        if info is None:
            log_event(
                logger,
                logging.INFO,
                "acp_agent_info_fallback",
                reason="agentInfo_missing",
            )
            self._agent_name = "opencode"
            self._agent_title = None
            self._agent_version = None
            return
        name = getattr(info, "name", None) or "opencode"
        # ACP Implementation: `name` is for programmatic use, `title` is the
        # human-readable display name (fall back to `name` when absent).
        title = getattr(info, "title", None)
        version = getattr(info, "version", None)
        self._agent_name = name
        self._agent_title = str(title) if title is not None else None
        self._agent_version = str(version) if version is not None else None
        log_event(
            logger,
            logging.INFO,
            "acp_agent_info_available",
            name=name,
            version=self._agent_version or "",
        )

    def _ingest_notification(self, dumped: dict[str, Any]) -> None:
        """Route session/update payloads into the capability state."""
        if not isinstance(dumped, dict):
            return
        kind = dumped.get("sessionUpdate")
        if kind == "config_option_update":
            options = dumped.get("configOptions") or dumped.get("options") or []
            if isinstance(options, list):
                self._capabilities.ingest_config_options(options)
        elif kind == "current_mode_update":
            mode_id = dumped.get("modeId")
            if isinstance(mode_id, str):
                self._capabilities.ingest_current_mode_update(mode_id)
        elif kind == "available_commands_update":
            commands = dumped.get("availableCommands")
            if isinstance(commands, list):
                self._capabilities.ingest_commands(commands)
        # Everything else already flowed out as raw debug events.

    async def select(
        self, kind: SelectionKind, value_id: str
    ) -> SelectionResult:
        """Apply a selection using runtime-provided config ids only.

        The authoritative echo (config_option_update / mode state) replaces
        local views; failures return a correlated non-applied result.

        ``agent`` maps to ACP session modes: OpenCode exposes its agents
        (build, plan, custom profiles) as modes, so selecting an agent is a
        mode selection. Selecting the already-active mode is a no-op.
        """
        if kind == "agent":
            current = self._capabilities.selected_mode
            if current is not None and value_id == current:
                return SelectionResult(
                    kind=kind,
                    applied=True,
                    message="Agent selection is a no-op: the mode is already active.",
                )
            kind = "mode"
        if not self._connection or not self._session_id:
            return SelectionResult(kind=kind, applied=False, message="ACP session is not ready.")
        caps = self._capabilities
        try:
            if kind == "mode" and caps.mode_config_id is None:
                await self._connection.set_session_mode(
                    session_id=self._session_id, mode_id=value_id
                )
                caps.apply_selection_locally(kind, value_id)
                return SelectionResult(kind=kind, applied=True,
                                       message="Legacy set_session_mode accepted.")
            config_id = {
                "model": caps.model_config_id,
                "thinking": caps.thought_level_config_id,
            }.get(kind) if kind != "mode" else caps.mode_config_id
            if not config_id:
                return SelectionResult(
                    kind=kind,
                    applied=False,
                    message=f"No {kind} config option was announced by the runtime.",
                )
            result = await self._connection.set_config_option(
                session_id=self._session_id, config_id=config_id, value=value_id
            )
            dumped = jsonable_model(result)
            if isinstance(dumped, dict):
                options = dumped.get("configOptions")
                if isinstance(options, list):
                    caps.ingest_config_options(options)
            caps.apply_selection_locally(kind, value_id)
            return SelectionResult(
                kind=kind, applied=True, message="Runtime accepted the selection."
            )
        except Exception as exc:
            return SelectionResult(
                kind=kind, applied=False, message=f"Selection failed: {exc}"
            )

    async def _send(self, event: dict[str, Any]) -> None:
        if self._emit:
            await self._emit(event)

    async def _emit_commands_available(self) -> None:
        """Forward the current command list to the UI as a Protocol v1 event.

        ``available_commands_update`` arrives after session creation, so the
        startup snapshot misses it; this pushes the runtime list to the UI.
        """
        await self._send(
            {
                "type": "commands_available",
                "available": True,
                "commands": [command_item(c) for c in self._capabilities.commands.items],
            }
        )


__all__ = ["OpenCodeSession", "OpenCodeAcpAdapter"]

OpenCodeAcpAdapter = OpenCodeSession
