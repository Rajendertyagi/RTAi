"""Generic ACP session: spawn, lifecycle and event translation.

This is the shared core. It implements the whole :class:`AgentAdapter`
contract against the ACP specification, so a new ACP-backed agent only needs
to say how to find its executable:

    class MyAgentSession(AcpSession):
        default_agent_name = "myagent"

        def resolve_executable(self) -> str:
            found = shutil.which("myagent")
            if not found:
                raise RuntimeError("myagent was not found in PATH")
            return found

Everything else - permission prompts with full tool detail, tool call events,
capability discovery from live config options, selection, cancellation and
process ownership - is inherited unchanged.
"""

from __future__ import annotations

import contextlib
import logging
import os
from pathlib import Path
from typing import Any

from ...core.protocol import acp_chunk_kind, jsonable_model, text_from_acp_chunk
from ...logging_config import log_event, short_id
from ..base import AgentAdapter, Emit, SelectionKind, SelectionResult
from ..capabilities import (
    AgentDescriptor,
    CapabilitySection,
    CapabilitySnapshot,
    SessionCapabilities,
    UnavailabilityReason,
    UnavailableCapability,
)
from ..opencode.capability_mapper import AcpCapabilityState, command_item
from ..owned_process import OwnedProcess
from .client import create_client_class
from .mapping import (
    TERMINAL_STATUSES,
    map_tool_content,
    map_tool_locations,
    map_tool_status,
)

logger = logging.getLogger(__name__)

_PHASE_MESSAGE = "Runtime capability discovery arrives in Phase 2A-B."


def _capability_present(container: Any, field: str) -> bool | None:
    """True when a capability object is present, False when absent, None unknown."""
    if container is None:
        return None
    return getattr(container, field, None) is not None


class AcpSession(AgentAdapter):
    """Adapter around the official ACP Python SDK for one agent child process.

    The child spawned here is the only process this instance ever touches; its
    handle is retained in an :class:`OwnedProcess` so cleanup stays scoped to
    what RTAI created (ADR-0006).
    """

    # --- Subclass hooks -------------------------------------------------
    # Name used when the agent does not announce an identity of its own.
    default_agent_name: str = "agent"
    # Arguments passed to the executable to select its ACP subcommand.
    extra_args: tuple[str, ...] = ("acp",)

    def resolve_executable(self) -> str:
        """Return the path to this agent's executable.

        Subclasses must override this. Raising RuntimeError with an actionable
        message is the expected way to report a missing binary.
        """
        raise NotImplementedError(
            f"{type(self).__name__} must implement resolve_executable()."
        )

    # --- Lifecycle ------------------------------------------------------
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
        self._session_caps: SessionCapabilities | None = None
        self._pending_permissions: dict[str, Any] = {}
        # Tool call ids already announced via tool_start; used to distinguish
        # the first sighting from subsequent streaming/final updates.
        self._seen_tool_calls: set[str] = set()
        # Open streaming content part. A part is identified by a session-local
        # counter rather than ACP's messageId: every chunk of one ACP message
        # shares a messageId, so messageId alone cannot separate a thinking
        # run from the reply that follows it. Rolling a new id whenever the
        # chunk kind changes is what lets thinking and text interleave.
        self._open_part_id: str | None = None
        self._open_part_kind: str | None = None
        self._part_seq = 0

    async def start(self, cwd: Path, emit: Emit) -> None:
        try:
            from acp import PROTOCOL_VERSION, spawn_agent_process
        except ImportError as exc:
            raise RuntimeError(
                "ACP SDK is missing. Run: pip install -r requirements.txt"
            ) from exc

        executable = self.resolve_executable()

        log_event(
            logger,
            logging.INFO,
            "acp_spawn_requested",
            executable=Path(executable).name,
            **({"executable_path": executable} if logger.isEnabledFor(logging.DEBUG) else {}),
        )

        self._emit = emit
        client_cls = create_client_class()

        # Runtime note: Client has no __abstractmethods__ on the pinned SDK,
        # so partial implementations work. The class is built by
        # create_client_class(), which also keeps the SDK import lazy.
        self._context = spawn_agent_process(
            client_cls(self),
            executable,
            *self.extra_args,
            env=os.environ.copy(),
        )
        self._connection, process = await self._context.__aenter__()
        argv = [executable, *self.extra_args]
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
            self._session_caps = self._discover_session_capabilities(init_response)
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
        # The turn is over, so whatever part was streaming is finished too.
        await self._close_open_part()
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
        self._seen_tool_calls.clear()
        self._open_part_id = None
        self._open_part_kind = None
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

    # --- Capabilities ---------------------------------------------------
    def _pending_section(self) -> CapabilitySection[Any]:
        return CapabilitySection(
            items=(),
            unavailable=UnavailableCapability(
                UnavailabilityReason.PENDING_DISCOVERY, _PHASE_MESSAGE
            ),
        )

    def capability_snapshot(self) -> CapabilitySnapshot:
        fallback = self.default_agent_name
        if not self._initialized:
            agent: AgentDescriptor | UnavailableCapability = UnavailableCapability(
                UnavailabilityReason.PENDING_DISCOVERY,
                "Agent identity becomes available after initialization.",
            )
        else:
            name = self._agent_name or fallback
            # ACP exposes exactly one agent identity (agentInfo). `name` is the
            # programmatic id; `title` is the display label when provided.
            agent = AgentDescriptor(id=name.lower(), label=self._agent_title or name)
        if not self._initialized:
            return CapabilitySnapshot(
                source=f"acp:{(self._agent_name or fallback).lower()}",
                agent=agent,
                models=self._pending_section(),
                modes=self._pending_section(),
                thinking_options=self._pending_section(),
                commands=self._pending_section(),
            )
        caps = self._capabilities
        # Agents are exposed through ACP as session modes (OpenCode does this
        # for build, plan and locally configured profiles), so the agents
        # section mirrors the modes. The single agentInfo identity stays on
        # snapshot.agent and is surfaced separately (agent_info / status bar).
        agents = CapabilitySection(
            items=tuple(
                AgentDescriptor(id=m.id, label=m.label, description=m.description)
                for m in caps.modes.items
            )
        )
        if caps.selected_mode is not None:
            caps.selected_agent = caps.selected_mode
        return CapabilitySnapshot(
            source=f"acp:{(self._agent_name or fallback).lower()}",
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
            sessions=(
                self._session_caps
                if self._session_caps is not None
                else UnavailableCapability(
                    UnavailabilityReason.PENDING_DISCOVERY,
                    "Session feature flags arrive with the initialize response.",
                )
            ),
        )

    # --- Internals ------------------------------------------------------
    async def _close_context(self) -> None:
        if self._context is not None:
            with contextlib.suppress(Exception):
                await self._context.__aexit__(None, None, None)

    def _discover_session_capabilities(self, init_response: Any) -> SessionCapabilities:
        """Read session lifecycle support from the initialize response.

        Capability-state only: this records what the agent advertised but makes
        no lifecycle wire calls. ACP requires these capability checks before
        calling ``session/list``, ``session/load`` or ``session/resume``, so the
        flags are surfaced here for the (deferred) resume entry point.
        """
        caps = getattr(init_response, "agent_capabilities", None)
        if caps is None:
            return SessionCapabilities()
        load = getattr(caps, "load_session", None)
        session_caps = getattr(caps, "session_capabilities", None)
        return SessionCapabilities(
            load=bool(load) if load is not None else None,
            list_sessions=_capability_present(session_caps, "list"),
            resume=_capability_present(session_caps, "resume"),
            close=_capability_present(session_caps, "close"),
            delete=_capability_present(session_caps, "delete"),
            additional_directories=_capability_present(
                session_caps, "additional_directories"
            ),
        )

    def _capture_agent_identity(self, init_response: Any) -> None:
        info = getattr(init_response, "agentInfo", None)
        if info is None:
            log_event(
                logger,
                logging.INFO,
                "acp_agent_info_fallback",
                reason="agentInfo_missing",
            )
            self._agent_name = self.default_agent_name
            self._agent_title = None
            self._agent_version = None
            return
        name = getattr(info, "name", None) or self.default_agent_name
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

    async def _close_open_part(self) -> None:
        """Close the open content part, if any."""
        if self._open_part_id is None:
            return
        await self._send({"type": "part_done", "part_id": self._open_part_id})
        self._open_part_id = None
        self._open_part_kind = None

    async def _emit_content_part(self, update: Any) -> None:
        """Stream an ACP content chunk as part_start / part_delta events.

        Both ``AgentMessageChunk`` (the reply) and ``AgentThoughtChunk``
        (chain-of-thought) reach the timeline here. Thinking was previously
        dropped outright because only the message chunk was recognised.

        A new part opens whenever the chunk kind changes, so a run of thinking
        followed by a reply followed by more thinking becomes three parts in
        true chronological order.
        """
        kind = acp_chunk_kind(update)
        if kind is None:
            return

        if kind != self._open_part_kind:
            await self._close_open_part()
            self._part_seq += 1
            self._open_part_id = f"part-{self._part_seq}"
            self._open_part_kind = kind
            await self._send(
                {
                    "type": "part_start",
                    "part_id": self._open_part_id,
                    "part_type": kind,
                }
            )

        text = text_from_acp_chunk(update)
        if not text:
            return
        await self._send(
            {"type": "part_delta", "part_id": self._open_part_id, "text": text}
        )
        # Legacy path: the UI still renders one concatenated text blob until
        # the frontend moves to parts. Only the reply belongs in it - thinking
        # was never part of it before, so it stays out.
        if kind == "text":
            await self._send({"type": "delta", "text": text})

    async def _emit_tool_event(self, dumped: dict[str, Any]) -> None:
        """Map ACP tool-call session updates to Protocol v1 tool events.

        ACP announces tool activity through ``tool_call`` (ToolCallStart) and
        ``tool_call_update`` (ToolCallProgress) session updates. The first
        sighting of a tool call id becomes ``tool_start``; in-progress updates
        stream as ``tool_update``; completed/failed updates close with
        ``tool_result``. Content blocks and locations are forwarded in a typed
        shape the UI renders directly.
        """
        if not isinstance(dumped, dict):
            return
        session_update = dumped.get("sessionUpdate")
        # Accept an explicitly named tool update, or a bare ToolCallUpdate that
        # carries a toolCallId plus at least one recognisable tool field.
        is_named_tool_update = session_update in ("tool_call", "tool_call_update")
        has_tool_marker = "toolCallId" in dumped and any(
            key in dumped
            for key in ("kind", "status", "title", "content", "locations", "rawInput")
        )
        if not is_named_tool_update and not has_tool_marker:
            return
        tool_call_id = dumped.get("toolCallId")
        if not isinstance(tool_call_id, str) or not tool_call_id:
            return
        status = map_tool_status(dumped.get("status"))
        content = map_tool_content(dumped.get("content"))
        locations = map_tool_locations(dumped.get("locations"))

        if tool_call_id not in self._seen_tool_calls:
            self._seen_tool_calls.add(tool_call_id)
            event: dict[str, Any] = {
                "type": "tool_start",
                "tool_call_id": tool_call_id,
                "title": dumped.get("title") or "tool",
                "status": status or "running",
            }
            kind = dumped.get("kind")
            if isinstance(kind, str):
                event["kind"] = kind
            if locations:
                event["locations"] = locations
            if "rawInput" in dumped:
                event["raw_input"] = dumped.get("rawInput")
            await self._send(event)
            return

        if status in TERMINAL_STATUSES:
            event = {
                "type": "tool_result",
                "tool_call_id": tool_call_id,
                "status": status,
            }
            if content:
                event["content"] = content
            if locations:
                event["locations"] = locations
            await self._send(event)
            return

        event = {
            "type": "tool_update",
            "tool_call_id": tool_call_id,
            "status": status or "running",
        }
        if content:
            event["content"] = content
        if locations:
            event["locations"] = locations
        await self._send(event)

    async def select(
        self, kind: SelectionKind, value_id: str
    ) -> SelectionResult:
        """Apply a selection using runtime-provided config ids only.

        The authoritative echo (config_option_update / mode state) replaces
        local views; failures return a correlated non-applied result.

        ``agent`` maps to ACP session modes: agents are exposed as modes, so
        selecting an agent is a mode selection. Selecting the already-active
        mode is a no-op.
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


__all__ = ["AcpSession"]
