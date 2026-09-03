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

from ...core.protocol import (
    MCPServerConfig,
    acp_chunk_kind,
    jsonable_model,
    text_from_acp_chunk,
)
from ...logging_config import log_event, short_id
from ..base import AgentAdapter, Emit, SelectionKind, SelectionResult
from ..capabilities import (
    AgentDescriptor,
    AttachmentCapabilities,
    CapabilitySection,
    CapabilitySnapshot,
    SessionCapabilities,
    UnavailabilityReason,
    UnavailableCapability,
)
from ..opencode.capability_mapper import AcpCapabilityState, command_item
from ..owned_process import OwnedProcess
from ..prompt_content import PromptContent, PromptKind, validate_prompt_limits
from .client import create_client_class
from ...diagnostics import EVENT
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
        raise NotImplementedError(f"{type(self).__name__} must implement resolve_executable().")

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
        # Per-session diagnostics recorder (safe, ring-buffered). Linked by the
        # session entry; None until then so recording is a no-op beforehand.
        self.diag: Any = None
        # One-time guard so the safe model-option discovery event logs once.
        self._model_option_discovered: bool = False
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
        # Optional MCP servers to attach at session creation time.
        # Passed through to ACP new_session() when present.
        self._mcp_servers: list[MCPServerConfig] | None = None

    async def start(self, cwd: Path, emit: Emit) -> None:
        try:
            from acp import PROTOCOL_VERSION, spawn_agent_process
        except ImportError as exc:
            raise RuntimeError("ACP SDK is missing. Run: pip install -r requirements.txt") from exc

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
            init_response = await self._connection.initialize(protocol_version=PROTOCOL_VERSION)
            self._capture_agent_identity(init_response)
            self._capabilities.ingest_prompt_capabilities(jsonable_model(init_response))
            session = await self._connection.new_session(
                cwd=str(cwd),
                mcp_servers=(
                    [
                        {
                            "name": s.name,
                            "command": s.command,
                            "args": list(s.args),
                            "env": s.env or {},
                            "cwd": s.cwd or "",
                        }
                        for s in self._mcp_servers
                    ]
                    if self._mcp_servers
                    else []
                ),
            )
            self._session_id = session.session_id
            self._record_diag(EVENT["SESSION_RESOLVED"], "info", session=short_id(self._session_id))
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
            self._maybe_record_model_discovery()
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
        # Re-assert the user's selected model so the next turn demonstrably uses
        # it. The ACP prompt request carries no model field, so the effective
        # model depends entirely on the session config applied here through the
        # single authorized set_config_option path (the same path select() uses).
        self._record_diag(EVENT["PROMPT_STARTED"], "info", session=short_id(self._session_id), text_length=len(text))
        try:
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
            await self._close_open_part()
            await self._send({"type": "done"})
            self._record_diag(EVENT["PROMPT_COMPLETED"], "info", session=short_id(self._session_id))
        except Exception:
            self._record_diag(EVENT["PROMPT_FAILED"], "error", session=short_id(self._session_id))
            raise

    async def submit_prompt_content(self, content: list[PromptContent]) -> None:
        """Send a multi-block prompt with validated attachments.

        Converts RTAI domain blocks to ACP SDK ContentBlock objects, checks
        each block against the negotiated agent capabilities, and dispatches
        a single prompt call. Rejects the entire prompt if any block is
        unsupported — no partial submission.
        """
        if not self._connection or not self._session_id:
            raise RuntimeError("ACP session is not ready")
        if not content:
            raise ValueError("prompt content must not be empty")

        caps = self._capabilities
        # Validate RTAI safety limits before any SDK interaction.
        validate_prompt_limits(content)
        self._record_diag(EVENT["PROMPT_STARTED"], "info", session=short_id(self._session_id))

        # Check capability support for each block kind — reject entirely on
        # first unsupported kind rather than silently dropping or downgrading.
        for block in content:
            if block.kind == PromptKind.TEXT:
                continue
            if block.kind == PromptKind.IMAGE and not caps.attachment_images:
                raise RuntimeError("attachment rejected: image not supported by this agent")
            if block.kind == PromptKind.AUDIO and not caps.attachment_audio:
                raise RuntimeError("attachment rejected: audio not supported by this agent")
            if (
                block.kind in (PromptKind.EMBEDDED_TEXT, PromptKind.EMBEDDED_BLOB)
                and not caps.attachment_embedded
            ):
                raise RuntimeError(
                    "attachment rejected: embedded resources not supported by this agent"
                )
            # RESOURCE_LINK is baseline per ACP v1 and always supported.

        # Convert to ACP SDK ContentBlock objects.
        from acp import (
            audio_block,
            embedded_blob_resource,
            embedded_text_resource,
            image_block,
            resource_link_block,
            text_block,
        )
        from acp.schema import EmbeddedResourceContentBlock

        blocks: list[Any] = []
        for block in content:
            if block.kind == PromptKind.TEXT:
                blocks.append(text_block(block.text or ""))
            elif block.kind == PromptKind.IMAGE:
                assert block.data is not None
                blocks.append(
                    image_block(
                        block.data.decode("latin-1"),  # binary-safe round-trip
                        block.mime_type or "",
                    )
                )
            elif block.kind == PromptKind.AUDIO:
                assert block.data is not None
                blocks.append(
                    audio_block(
                        block.data.decode("latin-1"),
                        block.mime_type or "",
                    )
                )
            elif block.kind == PromptKind.RESOURCE_LINK:
                blocks.append(
                    resource_link_block(
                        block.name,
                        block.uri or "",
                        mime_type=block.mime_type,
                    )
                )
            elif block.kind == PromptKind.EMBEDDED_TEXT:
                blocks.append(
                    EmbeddedResourceContentBlock(
                        type="resource",
                        resource=embedded_text_resource(
                            f"rtai://{block.name}",
                            block.text or "",
                            mime_type=block.mime_type,
                        ),
                    )
                )
            elif block.kind == PromptKind.EMBEDDED_BLOB:
                assert block.data is not None
                blocks.append(
                    EmbeddedResourceContentBlock(
                        type="resource",
                        resource=embedded_blob_resource(
                            f"rtai://{block.name}",
                            block.data.decode("latin-1"),
                            mime_type=block.mime_type,
                        ),
                    )
                )

        log_event(
            logger,
            logging.DEBUG,
            "acp_prompt_content_submitted",
            session=short_id(self._session_id),
            block_count=len(blocks),
            kinds=[b.kind.value for b in content],
            total_bytes=sum(b.size_bytes for b in content),
        )
        await self._connection.prompt(
            session_id=self._session_id,
            prompt=blocks,
        )
        log_event(
            logger,
            logging.DEBUG,
            "acp_turn_completed",
            session=short_id(self._session_id),
        )
        await self._close_open_part()
        await self._send({"type": "done"})

    async def cancel(self) -> None:
        self._record_diag(EVENT["PROMPT_CANCELLED"], "info")
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
        self._record_diag(EVENT["SESSION_CLOSED"], "info")
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
        self._record_diag(
            EVENT["PERMISSION_RESPONDED"], "info",
            permission=short_id(permission_request_id), option=short_id(option_id),
        )
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
                selected={},
                commands=self._pending_section(),
            )
        caps = self._capabilities
        # Agent identity and ACP session modes are different concepts. ACP
        # exposes exactly one agent identity (agentInfo) on snapshot.agent and
        # has no agent list or agent-switching method, so the agents section is
        # honestly unavailable instead of mirroring the modes (which created
        # fake agent choices and duplicated the Mode selector).
        agents = CapabilitySection(
            items=(),
            unavailable=UnavailableCapability(
                UnavailabilityReason.NOT_EXPOSED_BY_PROVIDER,
                "ACP exposes one agent identity; agents are not selectable on this adapter.",
            ),
        )
        # Attachment capabilities derived from ACP Initialize negotiation.
        # Resource links are baseline per ACP v1 spec; image/audio/embedded
        # are gated by agent promptCapabilities. RTAI safety limits are
        # reported alongside provider limits so the UI can enforce its own.
        ac = AttachmentCapabilities(
            block_types=tuple(
                k.value
                for k, flag in [
                    (PromptKind.RESOURCE_LINK, caps.attachment_resource_links),
                    (PromptKind.IMAGE, caps.attachment_images),
                    (PromptKind.AUDIO, caps.attachment_audio),
                    (PromptKind.EMBEDDED_TEXT, caps.attachment_embedded),
                    (PromptKind.EMBEDDED_BLOB, caps.attachment_embedded),
                ]
                if flag
            ),
            max_size_bytes=None,  # provider does not advertise size limits
            resource_links=caps.attachment_resource_links,
            images=caps.attachment_images,
            audio=caps.attachment_audio,
            embedded_resources=caps.attachment_embedded,
            max_item_bytes=5 * 1024 * 1024,
            max_total_bytes=10 * 1024 * 1024,
            max_count=10,
        )
        return CapabilitySnapshot(
            source=f"acp:{(self._agent_name or fallback).lower()}",
            agent=agent,
            agents=agents,
            models=caps.models,
            modes=caps.modes,
            thinking_options=caps.thinking,
            # No "agent" selection exists on ACP: the single agentInfo
            # identity is projected from snapshot.agent, not from selected.
            selected={
                "model": caps.selected_model,
                "mode": caps.selected_mode,
                "thinking": caps.selected_thinking,
            },
            commands=caps.commands,
            attachments=ac,
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
            additional_directories=_capability_present(session_caps, "additional_directories"),
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
                self._maybe_record_model_discovery()
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
        await self._send({"type": "part_delta", "part_id": self._open_part_id, "text": text})

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
            key in dumped for key in ("kind", "status", "title", "content", "locations", "rawInput")
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

    async def select(self, kind: SelectionKind, value_id: str) -> SelectionResult:
        """Apply a selection using runtime-provided config ids only.

        Selections are echo-authoritative: a value becomes selected only when
        the runtime echo reports it; failures return a non-applied result.

        ACP has no agent selection: ``kind == "agent"`` is answered with a
        non-applied result instead of being redirected to the mode config.
        """
        if not self._connection or not self._session_id:
            return SelectionResult(kind=kind, applied=False, message="ACP session is not ready.")
        if kind == "agent":
            return SelectionResult(
                kind=kind,
                applied=False,
                message=(
                    "ACP exposes one agent identity; agent switching is not "
                    "supported by this adapter."
                ),
            )
        caps = self._capabilities
        self._record_diag(EVENT["CAPABILITY_SELECTION_REQUESTED"], "info", kind=kind)
        try:
            if kind == "mode" and caps.mode_config_id is None:
                # Legacy fallback. ACP session/set_mode returns only _meta —
                # no confirmed current mode — so there is nothing
                # authoritative to verify against (SDK SetSessionModeResponse).
                await self._connection.set_session_mode(
                    session_id=self._session_id, mode_id=value_id
                )
                # No local write: without an echo there is no confirmation,
                # so the prior confirmed mode stays selected. The agent's
                # current_mode_update notification remains the authoritative
                # confirmation and is projected on the next refresh/snapshot.
                self._record_diag(
                    EVENT["CAPABILITY_SELECTION_UNCONFIRMED"],
                    "warn",
                    kind=kind,
                    status="legacy_set_mode_no_echo",
                )
                return SelectionResult(
                    kind=kind,
                    applied=False,
                    message=(
                        "Mode change sent via the legacy session/set_mode "
                        "request; the runtime has not confirmed it, so the "
                        "previously confirmed mode stays selected."
                    ),
                )
            config_id = (
                {
                    "model": caps.model_config_id,
                    "thinking": caps.thought_level_config_id,
                }.get(kind)
                if kind != "mode"
                else caps.mode_config_id
            )
            if not config_id:
                return SelectionResult(
                    kind=kind,
                    applied=False,
                    message=f"No {kind} config option was announced by the runtime.",
                )
            self._record_diag(EVENT["ACP_CONFIG_OPTION_SENT"], "info", kind=kind)
            try:
                result = await self._connection.set_config_option(
                    session_id=self._session_id, config_id=config_id, value=value_id
                )
                self._record_diag(EVENT["ACP_CONFIG_OPTION_CONFIRMED"], "info", kind=kind)
            except Exception:
                self._record_diag(EVENT["ACP_CONFIG_OPTION_FAILED"], "error", kind=kind)
                raise
            dumped = jsonable_model(result)
            options = dumped.get("configOptions") if isinstance(dumped, dict) else None
            self._record_diag(EVENT["ACP_CONFIG_OPTION_ECHO"], "info", kind=kind)
            if kind == "model":
                # Authoritative-only model selection: the active model is updated
                # exclusively from the echoed config options, and applied only if
                # the echo reports the same config id with the requested value.
                self._maybe_record_model_discovery()
                confirmed = False
                if isinstance(options, list):
                    summary = caps.ingest_config_options(options)
                    confirmed = bool(summary.get("model_present")) and (
                        caps.model_config_id == config_id
                        and caps.selected_model == value_id
                    )
                if confirmed:
                    self._record_diag(EVENT["MODEL_ECHO_MATCH"], "info", kind="model")
                    self._record_diag(EVENT["MODEL_CONFIRMED"], "info", kind="model")
                    return SelectionResult(
                        kind=kind, applied=True,
                        message="Runtime confirmed the selected model.",
                    )
                # Missing/malformed/other-id/other-value echo: keep the prior
                # confirmed model; do NOT overwrite the badge.
                self._record_diag(EVENT["MODEL_ECHO_MISMATCH"], "warn", kind="model")
                return SelectionResult(
                    kind=kind, applied=False,
                    message=(
                        "Runtime did not confirm the requested model; the "
                        "previously confirmed model stays selected."
                    ),
                )
            if isinstance(options, list):
                caps.ingest_config_options(options)
                confirmed_selected, confirmed_config_id = (
                    (caps.selected_mode, caps.mode_config_id)
                    if kind == "mode"
                    else (caps.selected_thinking, caps.thought_level_config_id)
                )
                if (
                    confirmed_selected == value_id
                    and confirmed_config_id == config_id
                ):
                    self._record_diag(
                        EVENT["CAPABILITY_ECHO_MATCH"], "info", kind=kind
                    )
                    return SelectionResult(
                        kind=kind,
                        applied=True,
                        message="Runtime confirmed the selection.",
                    )
                self._record_diag(
                    EVENT["CAPABILITY_ECHO_MISMATCH"], "warn", kind=kind
                )
                return SelectionResult(
                    kind=kind,
                    applied=False,
                    message=(
                        "Runtime did not confirm the requested "
                        f"{kind} selection; the previously confirmed "
                        "selection stays."
                    ),
                )
            self._record_diag(
                EVENT["CAPABILITY_ECHO_MISMATCH"], "warn",
                kind=kind, status="echo_not_a_list",
            )
            return SelectionResult(
                kind=kind,
                applied=False,
                message=(
                    "Runtime response did not include config options, so the "
                    f"requested {kind} selection is not confirmed; the "
                    "previously confirmed selection stays."
                ),
            )
        except Exception as exc:
            return SelectionResult(kind=kind, applied=False, message=f"Selection failed: {exc}")

    def _maybe_record_model_discovery(self) -> None:
        """Record a safe, one-time model-option discovery event (category only)."""
        if self._model_option_discovered:
            return
        category = self._capabilities.discovered_model_category
        if category:
            self._record_diag(EVENT["MODEL_OPTION_DISCOVERED"], "info", category=category)
            self._model_option_discovered = True

    def _record_diag(self, event: str, level: str = "info", **fields: Any) -> None:
        """Record a safe diagnostic event if a recorder is linked (no-op otherwise)."""
        rec = getattr(self, "diag", None)
        if rec is not None:
            rec.record(event, level, **fields)

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
