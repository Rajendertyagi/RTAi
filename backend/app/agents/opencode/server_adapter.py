"""OpenCode Server adapter: app-owned `opencode serve` child over HTTP/SSE.

Ownership and safety (ADR-0006/0007/0008):

- The adapter ALWAYS launches its own `opencode serve` bound to 127.0.0.1 on
  a dynamically chosen private port; it never attaches to an existing server
  and accepts no external base URL.
- The exact child handle is retained in an ``OwnedProcess``; basic-auth
  credentials are handed to the child through environment variables only.
- Readiness waits for ``GET /global/health`` under a hard wall-clock deadline
  measured with ``time.monotonic()`` (independent of any injected benchmark
  clock, so frozen clocks cannot extend or hang startup).
- Port allocation is inherently racy (the OS releases the ephemeral port
  before OpenCode binds it): bind/startup failures trigger a bounded retry
  with a freshly allocated port. Cleanup between attempts touches only the
  failed owned child.
- Shutdown is cooperative-first via the launcher's terminate-and-wait, with a
  timeout-bounded forced kill scoped to the stored handle.

Known upstream risk: OpenCode has reported cases where terminating `serve`
left descendant resources behind. RTAi closes its SSE connection and its own
child handle reliably, but complete descendant cleanup is NOT claimed until a
verified process-group / Windows Job Object strategy exists.

Capability discovery queries only documented endpoints; anything the running
server does not expose becomes an unavailable section with an exact reason.
Prompt streaming/cancellation are translated minimally for the later fair
benchmark - this adapter is NOT wired to the frontend in this phase.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Any, Protocol

from ...logging_config import log_event, short_id
from ..base import AgentAdapter, Emit, SelectionResult
from ..capabilities import (
    AgentDescriptor,
    CapabilitySection,
    CapabilitySnapshot,
    UnavailabilityReason,
    UnavailableCapability,
)
from ..owned_process import DEFAULT_FORCE_TIMEOUT_SECONDS, OwnedProcess
from .capability_mapper import (
    AcpCapabilityState,
    command_item,
    normalise_providers,
    server_models_from_providers,
    server_selected_model,
)
from .events import parse_sse_events
from .http_client import HttpTransport, StdlibHttpTransport, StreamError, basic_auth_header
from .launcher import ServerLaunchPlan, build_launch_plan

logger = logging.getLogger(__name__)

_READY_TIMEOUT_SECONDS = 20.0
_POLL_INTERVAL_SECONDS = 0.2
_BIND_RETRY_ATTEMPTS = 2


class ServerStartupError(RuntimeError):
    """Classified readiness failure."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


class ServerLauncher(Protocol):
    async def launch(self, plan: ServerLaunchPlan) -> tuple[OwnedProcess, Any]: ...


class StdlibServerLauncher:
    """Launches `opencode serve` via asyncio with per-child env overrides."""

    def __init__(self) -> None:
        self._force_timeout = DEFAULT_FORCE_TIMEOUT_SECONDS

    async def launch(
        self, plan: ServerLaunchPlan
    ) -> tuple[OwnedProcess, asyncio.subprocess.Process]:
        env = os.environ.copy()
        env.update(plan.env_overrides)
        # CREATE_NO_WINDOW exists only on Windows asyncio; guard via hasattr
        # instead of getattr-with-constant to keep static analysis exact.
        creation_flags = (
            asyncio.subprocess.CREATE_NO_WINDOW
            if hasattr(asyncio.subprocess, "CREATE_NO_WINDOW")
            else 0
        )
        process = await asyncio.create_subprocess_exec(
            *plan.argv,
            env=env,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            creationflags=creation_flags,
        )

        async def terminate_and_wait() -> None:
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), 5.0)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()

        owned = OwnedProcess(
            handle=process,
            pid=process.pid,
            argv=plan.argv,
            cooperative_close=terminate_and_wait,
            force_timeout_seconds=self._force_timeout,
        )
        return owned, process


class OpenCodeServerAdapter(AgentAdapter):
    """App-owned OpenCode headless-server integration (preferred candidate)."""

    def __init__(
        self,
        *,
        http: HttpTransport | None = None,
        launcher: ServerLauncher | None = None,
        opencode_bin: str | None = None,
        ready_timeout_seconds: float = _READY_TIMEOUT_SECONDS,
        poll_interval_seconds: float = _POLL_INTERVAL_SECONDS,
        bind_retry_attempts: int = _BIND_RETRY_ATTEMPTS,
        username: str | None = None,
        password: str | None = None,
        benchmark: Any = None,
    ) -> None:
        self._http: HttpTransport = http or StdlibHttpTransport()
        self._launcher = launcher or StdlibServerLauncher()
        self._opencode_bin = (
            opencode_bin
            or os.environ.get("OPENCODE_BIN")
            or shutil.which("opencode")
            or ""
        )
        self._ready_timeout = ready_timeout_seconds
        self._poll_interval = poll_interval_seconds
        self._bind_retry_attempts = bind_retry_attempts
        self._username = username or "opencode"
        self._password = password or ""
        self._benchmark = benchmark
        self._plan: ServerLaunchPlan | None = None
        self._owned: OwnedProcess | None = None
        self._session_id: str | None = None
        self._server_version: str | None = None
        self._emit: Emit | None = None
        self._capabilities = AcpCapabilityState()
        self._agents_section: CapabilitySection[AgentDescriptor] | None = None
        self._stream_task: asyncio.Task[None] | None = None
        self._initialized = False
        self._closing = False
        # Turn-scoped translation state (reset on each submit_prompt).
        self._awaiting_idle = False
        self._completed_emitted = False
        self._error_emitted = False
        self._sent_part_offsets: dict[str, int] = {}
        # Open streaming content part (text/reasoning). The server part id is
        # stable across updates, so it doubles as the protocol part id; a new
        # part opens whenever the part id or kind changes.
        self._open_part_id: str | None = None
        self._open_part_kind: str | None = None
        # Tool call ids already announced this turn (first sighting => tool_start).
        self._seen_tool_calls: set[str] = set()

    # -- lifecycle -----------------------------------------------------------

    async def start(self, cwd: Path, emit: Emit) -> None:
        self._emit = emit
        executable = (
            self._opencode_bin
            or os.environ.get("OPENCODE_BIN")
            or shutil.which("opencode")
        )
        if not executable:
            raise RuntimeError("OpenCode was not found in PATH (expected 'opencode')")

        log_event(
            logger,
            logging.INFO,
            "server_spawn_requested",
            executable=Path(executable).name,
            **({"executable_path": executable} if logger.isEnabledFor(logging.DEBUG) else {}),
        )

        attempts = 1 + max(0, self._bind_retry_attempts)
        last_error: Exception | None = None
        for attempt in range(attempts):
            plan = build_launch_plan(
                executable,
                username=self._username or None,
                password=self._password or None,
            )
            self._plan = plan
            log_event(
                logger,
                logging.DEBUG,
                "server_launch_prepared",
                attempt=attempt + 1,
                port=plan.port,
                base_url=plan.base_url,
            )
            owned, process = await self._launcher.launch(plan)
            self._owned = owned
            log_event(
                logger,
                logging.INFO,
                "server_child_started",
                pid=owned.pid,
                attempt=attempt + 1,
            )
            if self._benchmark is not None:
                self._benchmark.mark("startup")
            try:
                await self._wait_until_ready(plan, process)
            except ServerStartupError as exc:
                log_event(
                    logger,
                    logging.WARNING,
                    "server_startup_failed",
                    kind=exc.kind,
                    attempt=attempt + 1,
                )
                await self._shutdown_owned()
                last_error = exc
                # Bind/startup races get a fresh private port; auth failures
                # and exhausted retries do not.
                if exc.kind in {"bind_failed", "child_exited"} and attempt < attempts - 1:
                    continue
                raise RuntimeError(
                    f"OpenCode server startup failed ({exc.kind}): {exc}"
                ) from exc

            if self._benchmark is not None:
                self._benchmark.mark("ready")
            try:
                await self._create_session(cwd)
                if self._benchmark is not None:
                    self._benchmark.mark("session_created")
                await self._discover_capabilities()
                self._start_event_stream(plan)
                self._initialized = True
            except BaseException:
                await self._shutdown_owned()
                self._owned = None
                raise
            return
        raise RuntimeError(
            f"OpenCode server startup failed after {attempts} attempts: {last_error}"
        ) from last_error

    async def _wait_until_ready(
        self, plan: ServerLaunchPlan, process: Any
    ) -> None:
        """Hard wall-clock deadline; classifies timeout/auth/child-exit."""
        deadline = time.monotonic() + self._ready_timeout
        while True:
            exit_code = getattr(process, "returncode", None)
            if exit_code is not None:
                raise ServerStartupError(
                    "child_exited",
                    f"server exited during startup (code {exit_code})",
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ServerStartupError(
                    "timeout",
                    f"not ready within {self._ready_timeout}s",
                )
            request_timeout = min(self._poll_interval * 4, remaining)
            try:
                result = await self._http.request(
                    "GET",
                    f"{plan.base_url}/global/health",
                    headers=self._headers(),
                    timeout_seconds=request_timeout,
                )
            except Exception:  # connection refused until the port opens
                pass
            else:
                if result.status in (401, 403):
                    raise ServerStartupError(
                        "auth_failed", f"health check returned HTTP {result.status}"
                    )
                if result.status == 200:
                    payload = result.json() or {}
                    version = payload.get("version")
                    # Tolerate documented compatible shapes: healthy may omit
                    # version; anything non-healthy keeps polling.
                    self._server_version = str(version) if version else None
                    if payload.get("healthy") is True:
                        log_event(
                            logger,
                            logging.INFO,
                            "server_ready",
                            version=self._server_version or "",
                        )
                        return
            await asyncio.sleep(self._poll_interval)

    async def _create_session(self, cwd: Path) -> None:
        result = await self._request_json(
            "POST", "/session", json_body={"title": "RTAI"}
        )
        session_id = result.get("id") if isinstance(result, dict) else None
        if not isinstance(session_id, str):
            raise RuntimeError("OpenCode server returned no session id")
        self._session_id = session_id
        if self._owned is not None:
            self._owned.attach_session(session_id)
        log_event(
            logger,
            logging.INFO,
            "server_session_created",
            session=short_id(session_id),
        )

    # -- capability discovery --------------------------------------------------

    async def _discover_capabilities(self) -> None:
        providers = await self._try_json("/config/providers")
        config = await self._try_json("/config")
        commands = await self._try_json("/command")
        agents_payload = await self._try_json("/agent")

        models = server_models_from_providers(providers)
        selected = server_selected_model(config)
        if models:
            self._capabilities.models = _section(models)
            # /config often carries no `model` field (nothing chosen yet), and
            # thinking options are derived from the selected model. Fall back to
            # the first reported model so reasoning variants still resolve.
            if selected in {None, ""} or selected not in {m.id for m in models}:
                selected = models[0].id
            self._capabilities.selected_model = selected
        else:
            self._capabilities.models = _missing_section(
                "GET /config/providers exposed no models"
            )

        thinking = self._thinking_section_for(
            providers, self._capabilities.selected_model
        )
        if not thinking.items and models:
            # Many models (e.g. the free tier) expose an empty `variants` map,
            # which would leave the Thinking control permanently unavailable.
            # Selection is a no-op on this adapter anyway (no documented
            # endpoint), so surface variants from the first model that has any.
            # Normalise once - the payload is large and models number in the
            # hundreds, so re-normalising per candidate is prohibitively slow.
            providers_map = normalise_providers(providers)
            for candidate in models:
                provider_id, _, model_key = candidate.id.partition("/")
                provider = providers_map.get(provider_id)
                if not isinstance(provider, dict):
                    continue
                container = provider.get("models")
                if not isinstance(container, dict):
                    continue
                entry = container.get(model_key)
                variants = entry.get("variants") if isinstance(entry, dict) else None
                if isinstance(variants, dict) and variants:
                    thinking = self._thinking_section_for(providers, candidate.id)
                    break
        self._capabilities.thinking = thinking

        # Agents populate the AGENTS section; they are behavioral profiles,
        # never modes and never models.
        agent_rows = agents_payload if isinstance(agents_payload, list) else []
        descriptors = [
            AgentDescriptor(
                id=str(row["name"]),
                label=str(row["name"]),
                description=str(row.get("description") or ""),
            )
            for row in agent_rows
            if isinstance(row, dict) and isinstance(row.get("name"), str)
        ]
        if descriptors:
            self._agents_section = _section(descriptors)
        else:
            self._agents_section = _missing_section("GET /agent exposed no agents")

        # Modes have no documented server endpoint: always unavailable here.
        self._capabilities.modes = _missing_section(
            "The OpenCode server API exposes no mode selection endpoint."
        )

        if isinstance(commands, list) and commands:
            self._capabilities.ingest_commands(commands)
        else:
            self._capabilities.commands = _missing_section(
                "GET /command returned no commands"
            )

        if self._server_version:
            self._benchmark_runtime_id("server_version", self._server_version)
        if selected:
            self._benchmark_runtime_id("model", selected)

        log_event(
            logger,
            logging.INFO,
            "server_capabilities_discovered",
            models=len(self._capabilities.models.items),
            commands=len(self._capabilities.commands.items),
            agents=len(self._agents_section.items) if self._agents_section else 0,
        )

    @staticmethod
    def _thinking_section_for(
        providers_payload: Any, selected_model: str | None
    ) -> CapabilitySection[Any]:
        """Thinking options come only from the selected model's variants."""
        options = _thinking_variants_for_model(providers_payload, selected_model)
        if options:
            from ..capabilities import ThinkingOption

            items = tuple(
                ThinkingOption(id=str(value), label=label)
                for value, label in options
            )
            return CapabilitySection(items=items)
        return _missing_section(
            "The selected model exposes no reasoning variants."
        )

    def _benchmark_runtime_id(self, key: str, value: str) -> None:
        if self._benchmark is not None:
            self._benchmark.set_runtime_id(key, value)

    # -- prompt / cancel ------------------------------------------------------

    async def submit_prompt(self, text: str) -> None:
        if not self._session_id:
            raise RuntimeError("OpenCode server session is not ready")
        self._sent_part_offsets.clear()
        self._open_part_id = None
        self._open_part_kind = None
        self._seen_tool_calls.clear()
        self._awaiting_idle = True
        self._completed_emitted = False
        self._error_emitted = False
        log_event(
            logger,
            logging.DEBUG,
            "server_prompt_submitted",
            session=short_id(self._session_id),
            text_length=len(text),
        )
        if self._benchmark is not None:
            self._benchmark.mark("prompt_accepted")
        body: dict[str, Any] = {"parts": [{"type": "text", "text": text}]}

        # prompt_async accepts model/agent/variant per request, which is how
        # selections are applied (there is no session-level selection endpoint).
        selected = self._capabilities.selected_model
        if selected:
            provider_id, _, model_id = selected.partition("/")
            if provider_id and model_id:
                body["model"] = {"providerID": provider_id, "modelID": model_id}
        if self._capabilities.selected_agent:
            body["agent"] = self._capabilities.selected_agent
        if self._capabilities.selected_thinking:
            body["variant"] = self._capabilities.selected_thinking

        await self._request_json(
            "POST",
            f"/session/{self._session_id}/prompt_async",
            json_body=body,
        )
        # prompt_async responds 204; streaming arrives via the event stream.

    async def cancel(self) -> None:
        if not self._session_id:
            return
        log_event(
            logger,
            logging.DEBUG,
            "server_cancel_requested",
            session=short_id(self._session_id),
        )
        await self._request_json("POST", f"/session/{self._session_id}/abort")
        if self._benchmark is not None:
            self._benchmark.mark("cancelled")

    async def _emit_commands_available(self) -> None:
        """Re-push the runtime command list to the UI.

        The startup snapshot already carries commands; this covers commands
        that land after session creation, mirroring what the ACP adapter does
        for ``available_commands_update``.
        """
        if self._emit is None:
            return
        commands = await self._try_json("/command")
        if isinstance(commands, list) and commands:
            self._capabilities.ingest_commands(commands)
            await self._emit(
                {
                    "type": "commands_available",
                    "available": True,
                    "commands": [
                        command_item(c) for c in self._capabilities.commands.items
                    ],
                }
            )

    # -- capabilities snapshot -------------------------------------------------

    def capability_snapshot(self) -> CapabilitySnapshot:
        if not self._initialized:
            return CapabilitySnapshot(source="opencode-server")
        agent = AgentDescriptor(id="opencode", label="opencode")
        snapshot_kwargs: dict[str, Any] = {
            "source": "opencode-server",
            "agent": agent,
            "models": self._capabilities.models,
            "modes": self._capabilities.modes,
            "thinking_options": self._capabilities.thinking,
            "commands": self._capabilities.commands,
            "attachments": UnavailableCapability(
                UnavailabilityReason.NOT_EXPOSED_BY_PROVIDER,
                "The OpenCode server API exposes no attachment size/type limits.",
            ),
            "sessions": UnavailableCapability(
                UnavailabilityReason.NOT_EXPOSED_BY_PROVIDER,
                "The OpenCode server API exposes no session list/load/resume "
                "endpoints; session lifecycle is not available on this adapter.",
            ),
        }
        if self._agents_section is not None:
            snapshot_kwargs["agents"] = self._agents_section
        return CapabilitySnapshot(**snapshot_kwargs)

    def owned_process(self) -> OwnedProcess | None:
        return self._owned

    async def select(self, kind: str, value_id: str) -> SelectionResult:
        """Record a model / agent / thinking choice for subsequent prompts.

        The OpenCode server exposes no session-level selection endpoint, but
        ``POST /session/{id}/prompt_async`` accepts ``model``, ``agent`` and
        ``variant`` per request - so the choice is applied on the next prompt
        rather than being a no-op.
        """
        resolved = (
            "model"
            if kind == "model"
            else "mode"
            if kind == "mode"
            else "agent"
            if kind == "agent"
            else "thinking"
        )

        if resolved == "mode":
            return SelectionResult(
                kind="mode",
                applied=False,
                message="The OpenCode server API exposes no mode selection.",
            )

        if resolved == "agent":
            known = {a.id for a in self._agents_section.items} if self._agents_section else set()
            if known and value_id not in known:
                return SelectionResult(
                    kind="agent", applied=False, message=f"Unknown agent {value_id!r}."
                )
        elif resolved == "model":
            known = {m.id for m in self._capabilities.models.items}
            if known and value_id not in known:
                return SelectionResult(
                    kind="model", applied=False, message=f"Unknown model {value_id!r}."
                )
        elif resolved == "thinking":
            known = {t.id for t in self._capabilities.thinking.items}
            if known and value_id not in known:
                return SelectionResult(
                    kind="thinking", applied=False, message=f"Unknown thinking level {value_id!r}."
                )

        self._capabilities.apply_selection_locally(resolved, value_id)
        return SelectionResult(
            kind=resolved,  # type: ignore[arg-type]
            applied=True,
            message=(
                "Applied to the next prompt "
                "(the server has no session-level selection endpoint)."
            ),
        )

    async def close(self) -> None:
        self._closing = True
        log_event(logger, logging.INFO, "server_shutdown_requested")
        if self._stream_task is not None:
            self._stream_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._stream_task
            self._stream_task = None
        await self._shutdown_owned()

    # -- internals --------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        if self._plan is None:
            return {}
        return basic_auth_header(self._plan.username, self._plan.password)

    async def _request_json(self, method: str, path: str, json_body: Any = None) -> Any:
        assert self._plan is not None
        result = await self._http.request(
            method,
            f"{self._plan.base_url}{path}",
            headers=self._headers(),
            json_body=json_body,
        )
        if result.status >= 400:
            raise RuntimeError(f"{method} {path} failed with HTTP {result.status}")
        return result.json()

    async def _try_json(self, path: str) -> Any:
        try:
            return await self._request_json("GET", path)
        except RuntimeError:
            return None

    def _start_event_stream(self, plan: ServerLaunchPlan) -> None:
        self._stream_task = asyncio.get_running_loop().create_task(
            self._consume_events(plan)
        )

    # -- event stream ------------------------------------------------------------

    async def _consume_events(self, plan: ServerLaunchPlan) -> None:
        """Translate the official global event stream for the owned session.

        Terminal conditions: adapter ``close()`` (expected, quiet),
        ``server.instance.disposed`` (clean marker; fails an active turn),
        or unexpected stream end (normalized connection error + failed
        benchmark). Only ``session.idle`` completes a turn.
        """
        url = f"{plan.base_url}/event"
        headers = {**self._headers(), "Accept": "text/event-stream"}
        lines = self._http.stream_lines(url, headers=headers)
        log_event(logger, logging.INFO, "server_sse_opened")
        try:
            async for sse in parse_sse_events(lines):
                if self._closing:
                    break
                try:
                    payload = json.loads(sse.data)
                except json.JSONDecodeError:
                    payload = {"type": "raw.parse_error", "raw": sse.data[:200]}
                if not isinstance(payload, dict):
                    payload = {"type": "unknown", "properties": payload}
                event_type = str(payload.get("type") or "")
                props = payload.get("properties")
                properties: dict[str, Any] = (
                    props if isinstance(props, dict) else {}
                )
                log_event(
                    logger,
                    logging.DEBUG,
                    "server_sse_received",
                    event_type=event_type,
                )

                if await self._handle_global_event(event_type, properties):
                    continue
                if self._is_foreign_event(event_type, properties):
                    continue
                if await self._handle_turn_event(event_type, properties):
                    continue

                # Unknown events reach only normalized raw diagnostics.
                if self._emit is not None:
                    log_event(
                        logger,
                        logging.DEBUG,
                        "server_event_normalized",
                        event_type=event_type,
                    )
                    await self._emit(
                        {"type": "raw", "event": event_type, "data": properties}
                    )
        except StreamError as exc:
            # Production transport failures (connect/auth/content-type).
            log_event(
                logger,
                logging.ERROR,
                "server_stream_error",
                kind=exc.kind,
            )
            await self._fail_active_turn(f"event stream {exc.kind}: {exc}")
            if self._benchmark is not None:
                self._benchmark.fail(f"stream_{exc.kind}")

        # Unexpected end-of-stream without a terminal marker or close():
        # an SSE disconnect must never look like a silent success.
        if not self._closing and not self._completed_emitted:
            log_event(logger, logging.WARNING, "server_stream_terminated")
            await self._fail_active_turn(
                "OpenCode event stream terminated unexpectedly"
            )
            if self._benchmark is not None:
                self._benchmark.fail("stream_dropped")
        log_event(logger, logging.INFO, "server_sse_closed")

    async def _handle_global_event(self, event_type: str, properties: dict[str, Any]) -> bool:
        """Benign session-less events. Returns True when handled."""
        if event_type in {"server.connected", "server.heartbeat"}:
            return True
        if event_type == "server.instance.disposed":
            # Clean SSE terminal marker - but an in-flight prompt fails.
            self._closing = True
            if self._awaiting_idle:
                await self._fail_active_turn(
                    "OpenCode server instance was disposed mid-turn"
                )
                if self._benchmark is not None:
                    self._benchmark.fail("stream_dropped")
            return True
        if "command" in event_type.lower():
            # Command list changed after session creation - re-push it so the
            # UI picker stays current.
            await self._emit_commands_available()
            return True
        return False

    def _is_foreign_event(self, event_type: str, properties: dict[str, Any]) -> bool:
        session_id = _session_id_from(event_type, properties)
        if session_id is not None:
            return session_id != self._session_id
        return event_type not in {"server.connected", "server.heartbeat"}

    async def _handle_turn_event(
        self, event_type: str, properties: dict[str, Any]
    ) -> bool:
        """Returns True when the event was consumed by a turn handler."""
        if self._emit is None:
            return True
        if self._benchmark is not None:
            self._benchmark.mark("first_event")

        if event_type == "message.part.updated":
            raw_part = properties.get("part")
            part: dict[str, Any] = raw_part if isinstance(raw_part, dict) else {}
            part_type = part.get("type")
            if part_type == "tool":
                # A tool part ends any open content part: server parts are
                # complete objects, unlike ACP's shared-messageId chunks.
                await self._close_open_part()
                await self._emit_tool_event(part)
                return True
            if part_type not in ("text", "reasoning", None):
                # step-start/step-finish/snapshot/patch/file/subtask/... are
                # not streamed content, but they do end an open content part.
                await self._close_open_part()
                return True
            if part_type != "reasoning" and self._benchmark is not None:
                self._benchmark.mark("first_token")
            await self._emit_content_part(part, properties.get("delta"))
            return True

        if event_type == "session.idle":
            if self._awaiting_idle and not self._completed_emitted:
                self._completed_emitted = True
                self._awaiting_idle = False
                log_event(
                    logger,
                    logging.INFO,
                    "server_session_idle",
                    session=short_id(self._session_id),
                )
                if self._benchmark is not None:
                    self._benchmark.mark("completed")
                emitter = self._emit
                if emitter is not None:
                    await self._close_open_part()
                    await emitter({"type": "done"})
            return True

        if event_type == "session.error":
            if not self._error_emitted:
                self._error_emitted = True
                log_event(
                    logger,
                    logging.ERROR,
                    "server_session_error",
                    session=short_id(self._session_id),
                )
                if self._benchmark is not None:
                    self._benchmark.fail("provider_error")
                emitter = self._emit
                if emitter is not None:
                    err_props = properties.get("error")
                    message = (
                        err_props.get("message")
                        if isinstance(err_props, dict)
                        else None
                    ) or "session reported an error"
                    await self._close_open_part()
                    await emitter({"type": "error", "message": str(message)})
            return True

        return event_type == "session.status"  # informational only

    async def _fail_active_turn(self, message: str) -> None:
        if self._awaiting_idle and self._emit is not None:
            self._error_emitted = True
            await self._close_open_part()
            await self._emit({"type": "error", "message": message})
        # The caller records the precise benchmark failure reason so a single
        # drop is never counted twice.

    async def _close_open_part(self) -> None:
        """Close the open content part, if any."""
        if self._open_part_id is None:
            return
        if self._emit is not None:
            await self._emit({"type": "part_done", "part_id": self._open_part_id})
        self._open_part_id = None
        self._open_part_kind = None

    async def _emit_content_part(self, part: dict[str, Any], delta: Any) -> None:
        """Stream a server text/reasoning part as part_start / part_delta events.

        Mirrors the ACP adapter: a new part opens whenever the part id or kind
        changes, so thinking and reply text become separate parts in true
        chronological order. The legacy ``delta`` event is kept for text parts
        until the frontend moves fully to parts.
        """
        if self._emit is None:
            return
        part_type = part.get("type")
        if part_type is None:
            # Legacy fallback: a part without a type field is reply text.
            part_type = "text"
        if part_type not in ("text", "reasoning"):
            return
        part_id = part.get("id")
        part_key = str(part_id) if isinstance(part_id, str) else ""

        # Delta is preferred; otherwise fall back to the full text minus what
        # has already been sent for this part.
        if isinstance(delta, str):
            chunk = delta
            raw_text = part.get("text")
            if isinstance(raw_text, str):
                self._sent_part_offsets[part_key] = len(raw_text)
        else:
            raw_text = part.get("text")
            full_text: str = raw_text if isinstance(raw_text, str) else ""
            sent = self._sent_part_offsets.get(part_key, 0)
            chunk = full_text[sent:] if len(full_text) > sent else ""
            self._sent_part_offsets[part_key] = len(full_text)
        if not chunk:
            return

        if part_key:
            if part_key != self._open_part_id or part_type != self._open_part_kind:
                await self._close_open_part()
                self._open_part_id = part_key
                self._open_part_kind = part_type
                await self._emit(
                    {
                        "type": "part_start",
                        "part_id": part_key,
                        "part_type": part_type,
                    }
                )
            await self._emit(
                {"type": "part_delta", "part_id": part_key, "text": chunk}
            )
        # Legacy path: only the reply belongs in the concatenated text blob.
        if part_type == "text":
            await self._emit({"type": "delta", "text": chunk})

    async def _emit_tool_event(self, part: dict[str, Any]) -> None:
        """Map an OpenCode server tool part to Protocol v1 tool events.

        The server protocol announces tool activity through
        ``message.part.updated`` events whose part has ``type == "tool"``.
        The first sighting of a call id becomes ``tool_start``; running
        updates stream as ``tool_update``; completed/error states close with
        ``tool_result``. Mirrors the ACP adapter's mapping so both adapters
        emit the same protocol shape.
        """
        if self._emit is None:
            return
        call_id = part.get("callID")
        if not isinstance(call_id, str) or not call_id:
            return
        state = part.get("state")
        state = state if isinstance(state, dict) else {}
        status = _server_tool_status(state.get("status"))
        tool = part.get("tool")
        tool_name = tool if isinstance(tool, str) else "tool"
        title = state.get("title")
        title = title if isinstance(title, str) and title else tool_name
        content = _server_tool_content(state.get("output"))
        raw_input = state.get("input")

        if call_id not in self._seen_tool_calls:
            self._seen_tool_calls.add(call_id)
            event: dict[str, Any] = {
                "type": "tool_start",
                "tool_call_id": call_id,
                "title": title,
                "status": status or "running",
                "kind": tool_name,
            }
            if raw_input is not None:
                event["raw_input"] = raw_input
            await self._emit(event)
            return

        if status in ("success", "error"):
            event = {
                "type": "tool_result",
                "tool_call_id": call_id,
                "status": status,
            }
            if content:
                event["content"] = content
            await self._emit(event)
            return

        event = {
            "type": "tool_update",
            "tool_call_id": call_id,
            "status": status or "running",
        }
        if content:
            event["content"] = content
        await self._emit(event)

    async def _shutdown_owned(self) -> None:
        if self._owned is not None:
            pid = self._owned.pid
            await self._owned.close()
            log_event(logger, logging.INFO, "server_process_closed", pid=pid)
        self._owned = None
        self._initialized = False


def _session_id_from(event_type: str, properties: dict[str, Any]) -> str | None:
    direct = properties.get("sessionID")
    if isinstance(direct, str):
        return direct
    part = properties.get("part")
    if isinstance(part, dict):
        nested = part.get("sessionID")
        if isinstance(nested, str):
            return nested
    info = properties.get("info")
    if isinstance(info, dict):
        nested = info.get("sessionID")
        if isinstance(nested, str):
            return nested
    return None


def _server_tool_status(status: Any) -> str | None:
    """Map server ToolState.status to Protocol v1 ToolStatus."""
    if status == "pending":
        return "pending"
    if status == "running":
        return "running"
    if status == "completed":
        return "success"
    if status == "error":
        return "error"
    return None


def _server_tool_content(output: Any) -> list[dict[str, Any]] | None:
    """Map server tool output (string or block array) to content blocks."""
    if isinstance(output, str):
        return [{"type": "content", "text": output}] if output else None
    if isinstance(output, list):
        blocks: list[dict[str, Any]] = []
        for item in output:
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text")
                if isinstance(text, str) and text:
                    blocks.append({"type": "content", "text": text})
        return blocks or None
    return None



def _section(items: list[Any]) -> CapabilitySection[Any]:
    return CapabilitySection(items=tuple(items))


def _missing_section(message: str) -> CapabilitySection[Any]:
    return CapabilitySection(
        items=(),
        unavailable=UnavailableCapability(UnavailabilityReason.NOT_EXPOSED_BY_PROVIDER, message),
    )


def _thinking_variants_for_model(
    providers_payload: Any, model_id: str | None
) -> list[tuple[str, str]]:
    if not model_id:
        return []
    # The payload is {"providers": [...]} in practice, so normalise before
    # walking it - iterating the raw mapping yields no matches.
    for _provider_id, provider in normalise_providers(providers_payload).items():
        if not isinstance(provider, dict):
            continue
        models = provider.get("models")
        container = models.items() if isinstance(models, dict) else []
        for model_key, model in container:
            if not isinstance(model, dict):
                continue
            candidate = f"{_provider_id}/{model_key}"
            if candidate != model_id:
                continue
            variants = model.get("variants")
            if not isinstance(variants, dict):
                return []
            pairs: list[tuple[str, str]] = []
            for variant_value, variant_name in variants.items():
                label = (
                    variant_name
                    if isinstance(variant_name, str)
                    else str(variant_value).replace("_", " ").title()
                )
                pairs.append((str(variant_value), label))
            return pairs
    return []
