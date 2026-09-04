"""Assistant session registry: one long-lived AgentAdapter per threadId.

Reuses the existing ``AgentAdapterFactory`` and ``OwnedProcess`` lifecycle;
no copy of ``agents/`` code lives here.  Only the minimal registry required
for HTTP ``POST /assistant`` to continue the same ACP conversation is kept.
No Redis or distributed store — RTAI is a local single-user app.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...agents.base import AgentAdapter
from ...agents.factory import AgentAdapterFactory
from ...core.protocol import resolve_project_path
from ...logging_config import log_event, short_id
from .acp_state_projector import _permission_meta_from_event
from ...diagnostics import (
    EVENT,
    SessionDiagnosticsRecorder,
    get_diagnostics_hub,
)

logger = logging.getLogger(__name__)

# Idle timeout env var with conservative default (30 minutes) suitable for local desktop.
# Normal thinking turns (~tens of seconds) will not be killed.
IDLE_TIMEOUT_ENV = "RTAI_ASSISTANT_IDLE_TIMEOUT_SECONDS"
IDLE_TIMEOUT_DEFAULT_SECONDS = 1800
IDLE_CHECK_INTERVAL_SECONDS = 60


def _idle_timeout_seconds() -> float:
    raw = os.environ.get(IDLE_TIMEOUT_ENV, "").strip()
    if not raw:
        return float(IDLE_TIMEOUT_DEFAULT_SECONDS)
    try:
        v = float(raw)
        if v <= 0:
            return float(IDLE_TIMEOUT_DEFAULT_SECONDS)
        return v
    except ValueError:
        return float(IDLE_TIMEOUT_DEFAULT_SECONDS)


def _on_creation_task_done(session_key: str, task: asyncio.Task) -> None:
    """Named observer for creation tasks: retrieve exception exactly once.

    - Ignores actually cancelled tasks.
    - Safely logs every unexpected creation failure, including RuntimeError (real
      startup failure). Controlled closing/shutdown sentinel is a return value,
      not an exception, so it produces no log and no unobserved-exception warning.
    - Does not alter what active awaiters receive (they still get the exception
      via `await shield(task)`); this only marks the exception as retrieved so
      the event loop does not emit 'Task exception was never retrieved' if every
      waiter disappeared or was cancelled.
    """
    if task.cancelled():
        return
    try:
        exc = task.exception()
    except asyncio.CancelledError:
        return
    if exc is None:
        return
    # Real failure: log without payloads/credentials/cwd/prompts
    log_event(
        logger,
        logging.ERROR,
        "assistant_creation_failed",
        session=short_id(session_key) if isinstance(session_key, str) else "unknown",
        error=type(exc).__name__,
    )


@dataclass
class _PermissionEntry:
    permission_id: str
    tool_call_id: str
    option_kinds: dict[str, str]
    resolution: str | None = None  # None while pending, "resolved" after resolve
    selected_option_id: str | None = None


class PermissionRegistry:
    """Session-owned permission metadata.

    Single source of truth for which permission requests belong to the session,
    what options are valid, and whether they have been resolved. Replaces any
    frontend-stored pending-permission list. Cleared on turn finish, session
    close, idle expiry, and shutdown.
    """

    def __init__(self) -> None:
        self._entries: dict[str, _PermissionEntry] = {}

    def register(
        self,
        permission_id: str,
        tool_call_id: str,
        options: list[dict[str, Any]],
    ) -> _PermissionEntry | None:
        if not permission_id or not tool_call_id:
            return None
        existing = self._entries.get(permission_id)
        if existing is not None:
            # Re-emitted request: keep an already-resolved record; otherwise
            # refresh option metadata for the still-pending permission.
            if existing.resolution is None:
                existing.option_kinds = {o["id"]: o.get("kind", "") for o in options}
            return existing
        entry = _PermissionEntry(
            permission_id=permission_id,
            tool_call_id=tool_call_id,
            option_kinds={o["id"]: o.get("kind", "") for o in options},
        )
        self._entries[permission_id] = entry
        return entry

    def get(self, permission_id: str) -> _PermissionEntry | None:
        return self._entries.get(permission_id)

    def get_by_tool_call_id(self, tool_call_id: str) -> _PermissionEntry | None:
        for entry in self._entries.values():
            if entry.tool_call_id == tool_call_id:
                return entry
        return None

    def is_active(self, permission_id: str) -> bool:
        entry = self._entries.get(permission_id)
        return entry is not None and entry.resolution is None

    def resolve(self, permission_id: str, option_id: str) -> bool:
        entry = self._entries.get(permission_id)
        if entry is None:
            return False
        entry.resolution = "resolved"
        entry.selected_option_id = option_id
        return True

    def mark_expired(self, permission_id: str) -> bool:
        entry = self._entries.get(permission_id)
        if entry is None:
            return False
        entry.resolution = "expired"
        entry.selected_option_id = None
        return True

    def clear(self) -> None:
        self._entries.clear()


class AssistantTransportDispatch:
    """Stable public dispatch bridge owned by the session entry.

    Created before ``adapter.start()`` and passed once as the ``Emit`` callable.
    Per-turn, a fresh ``AcpStateProjector`` is bound while the session lock is
    held and unbound in ``finally``.  No ``adapter._emit`` mutation occurs.
    """

    def __init__(self) -> None:
        self._projector: Any | None = None
        self.permissions: PermissionRegistry = PermissionRegistry()
        self.diagnostics: DiagnosticsRecorder | None = None

    async def __call__(self, event: dict[str, Any]) -> None:
        if isinstance(event, dict) and event.get("type") == "permission_request":
            with contextlib.suppress(Exception):
                self._register_permission(event)
        proj = self._projector
        if proj is None:
            if logger.isEnabledFor(logging.DEBUG):
                log_event(
                    logger,
                    logging.DEBUG,
                    "assistant_event_without_projector",
                    event_type=str(event.get("type") if isinstance(event, dict) else "unknown"),
                )
            return
        await proj.handle(event)
        # Project the safe recent diagnostics into external state after every event.
        with contextlib.suppress(Exception):
            proj.refresh_diagnostics()
        # Update idle activity on every ACP event arrival
        try:
            session_key = getattr(proj, "session_key", None)
            if isinstance(session_key, str) and session_key:
                _touch_session_sync(session_key)
        except Exception:
            pass

    def bind(self, projector: Any) -> None:
        self._projector = projector
        # Link the registry so tool_result/done can re-synchronize approvals the
        # REST endpoint already resolved (no private-field access from projector).
        with contextlib.suppress(Exception):
            projector.permission_registry = self.permissions
            projector.diagnostics = self.diagnostics
        # Seed the external-state diagnostics snapshot at first bind, AFTER the
        # canonical recorder is linked, so the UI sees lifecycle events recorded
        # before the first ACP event arrives.
        with contextlib.suppress(Exception):
            self._projector.refresh_diagnostics()

    def unbind(self, projector: Any) -> None:
        if self._projector is projector:
            self._projector = None

    def clear(self) -> None:
        """Public clear: remove current projector without affecting a newly bound one.

        This is used only during session shutdown after the active turn has
        released its lock and unbound its own projector. At that point the
        current value should be None; if a new projector was somehow bound
        (should not happen while closing), clear is a no-op for that new
        projector only if we check identity. To be safe, clear simply resets
        to None, but callers must ensure no new bind has occurred while closing.
        """
        # Safe public clear — only clears the current value, no identity check
        # needed because closing state prevents new binds.
        self._projector = None

    def _register_permission(self, event: dict[str, Any]) -> None:
        """Record permission metadata from a permission_request protocol event.

        Uses the same extraction the projector uses for the official approval
        state, keeping a single source of truth for option ids/kinds.
        """
        meta = _permission_meta_from_event(event)
        if meta is None:
            return
        self.permissions.register(meta["permission_id"], meta["tool_call_id"], meta["options"])

    def set_approval_resolved(self, permission_id: str, option_id: str, approved: bool) -> bool:
        """Update the bound projector's approval state for a resolved permission.

        Returns False when no projector is bound (stream/session ended), so the
        caller can report an honest lifecycle conflict instead of claiming the
        approval was delivered.
        """
        proj = self._projector
        if proj is None:
            return False
        try:
            return proj.update_approval(permission_id, option_id, approved)
        except Exception:
            return False

    def set_approval_expired(self, permission_id: str, reason: str) -> bool:
        """Mark the bound projector's approval as expired (no approved/optionId)."""
        proj = self._projector
        if proj is None:
            return False
        try:
            return proj.set_approval_expired(permission_id, reason)
        except Exception:
            return False

    def clear_permissions(self) -> None:
        """Drop all permission metadata (turn finish / session close)."""
        self.permissions.clear()

    def is_approval_active(self, permission_id: str) -> bool:
        """True when a projector is bound and holds a pending approval with this id."""
        proj = self._projector
        if proj is None:
            return False
        try:
            return proj.has_approval(permission_id)
        except Exception:
            return False


class _ClosingMarker:
    """Transient tombstone placed in ``_sessions`` while a creation task is awaited
    for close. It makes a concurrent new request observe a closing session (the
    pre-stream check returns 409; get_or_create_adapter raises) so no second adapter
    is started for the same key. Removed once close_session finalizes.
    """

    state = "closing"


class AssistantSessionEntry:
    """Holds the owned adapter for one AssistantTransport thread."""

    def __init__(self, adapter: AgentAdapter, dispatch: AssistantTransportDispatch) -> None:
        self.adapter = adapter
        self.dispatch = dispatch
        self.lock = asyncio.Lock()
        # Dedicated lock for permission responses vs. turn cleanup. The active
        # prompt owns ``lock`` (the turn lock); permission responses must NOT
        # acquire it (would deadlock), so a separate lock serializes resolution
        # against turn-finally cleanup and session-close cleanup.
        self.permission_lock = asyncio.Lock()
        self.last_activity = time.monotonic()
        self.state: str = "active"  # active | closing | closed | close_failed
        self.close_task: asyncio.Task[bool] | None = None
        self.close_error: str | None = None
        self._closed = False

    def touch(self) -> None:
        self.last_activity = time.monotonic()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self.adapter.close()
        except Exception:
            log_event(logger, logging.WARNING, "assistant_session_close_failed")
        log_event(logger, logging.INFO, "assistant_session_closed")


# Registry keyed by stable session identity (threadId / state.sessionId).
_sessions: dict[str, AssistantSessionEntry | _ClosingMarker] = {}
_sessions_lock = asyncio.Lock()

# Per-session single-flight adapter creation. The creation *task* is registered
# under ``_sessions_lock``, but the slow ``adapter.start()`` I/O runs OUTSIDE any
# lock so a slow OpenCode startup on one session never blocks creation or requests
# for a different session. See ``get_or_create_adapter`` / ``_create_adapter_task``.
_creation_tasks: dict[str, asyncio.Task[AgentAdapter | None]] = {}

# Sentinel for controlled closing/shutdown completion (not an exception)
_CREATION_ABORTED = object()

# Set during application shutdown so in-flight creations tear down instead of
# registering a live session that cleanup_all would otherwise leak.
_shutting_down = False

# Periodic idle cleanup task
_idle_task: asyncio.Task[None] | None = None


def _touch_session_sync(session_key: str) -> None:
    entry = _sessions.get(session_key)
    if isinstance(entry, AssistantSessionEntry) and entry.state == "active":
        entry.touch()


def touch_session(session_key: str) -> None:
    """Update last activity for session_key if it exists and is active."""
    _touch_session_sync(session_key)


def _compute_session_counts() -> dict[str, int]:
    """Safe bounded counts from the session registry.

    Caller must already hold ``_sessions_lock`` (or accept a racy-but-harmless
    read). Counts are ints only — safe for browser diagnostics output.

    - liveSessions: entries in state "active"
    - creatingSessions: in-flight single-flight creation tasks (not yet done)
    - closingSessions: entries in state "closing" plus closing tombstones
    - liveAdapters: entries whose owned adapter has not been closed
    """
    live = 0
    closing = 0
    adapters = 0
    for entry in _sessions.values():
        if not isinstance(entry, AssistantSessionEntry):
            closing += 1  # _ClosingMarker tombstone: a close is in progress
            continue
        if entry.state == "active":
            live += 1
        elif entry.state == "closing":
            closing += 1
        if entry.state in ("active", "closing") and not entry._closed:
            adapters += 1
    creating = sum(1 for task in _creation_tasks.values() if not task.done())
    return {
        "liveSessions": live,
        "creatingSessions": creating,
        "closingSessions": closing,
        "liveAdapters": adapters,
    }


def registry_counts() -> dict[str, int]:
    """Read-only current safe counts for the global diagnostics endpoint.

    Sync and lock-free on purpose: all registry mutations happen on the event
    loop and this read performs no ``await``, so it cannot interleave with a
    mutation. Returns ints only — never session ids or adapter internals.
    """
    return _compute_session_counts()


async def _record_counts_event() -> None:
    """Record one safe ``app.counts`` event into the central hub.

    Exact owner point for count transitions: called by the session manager
    right after a create or close transition completes, so the hub's most
    recent ``app.counts`` event always reflects the registry after that
    transition. Values are bounded ints only.
    """
    try:
        async with _sessions_lock:
            counts = _compute_session_counts()
        with contextlib.suppress(Exception):
            get_diagnostics_hub().record(EVENT["APP_COUNTS"], "info", **counts)
    except Exception:
        pass


def _resolve_assistant_cwd(raw_state: Any | None, raw_config: Any | None) -> Path:
    """Derive the project folder for a new assistant session.

    Accepts ``cwd`` from ``state`` or ``config`` when present; otherwise
    falls back to ``RTAI_PROJECT_ROOT`` or the process working directory.
    Resolution failures fall back to a temp scratch folder behaviour.
    """
    candidates: list[str | None] = []
    if isinstance(raw_state, dict):
        candidates.append(raw_state.get("cwd"))
        candidates.append(raw_state.get("cwdPath"))
    if isinstance(raw_config, dict):
        candidates.append(raw_config.get("cwd"))
        candidates.append(raw_config.get("projectPath"))
    candidates.append(os.environ.get("RTAI_PROJECT_ROOT"))

    for raw in candidates:
        if isinstance(raw, str) and raw.strip():
            try:
                return resolve_project_path(raw)
            except ValueError:
                continue

    # Final fallback: process cwd; if not a valid project dir, use it anyway
    # so the adapter can decide.  Create a temp dir only if needed downstream.
    fallback = os.environ.get("RTAI_PROJECT_ROOT") or str(Path.cwd())
    try:
        return resolve_project_path(fallback)
    except ValueError:
        return Path.cwd()


async def get_or_create_adapter(
    session_key: str,
    *,
    factory: AgentAdapterFactory,
    state: Any | None,
    config: Any | None,
) -> AgentAdapter:
    """Return the long-lived adapter for *session_key*, creating it if needed.

    Per-session SINGLE-FLIGHT creation: under ``_sessions_lock`` we either return
    an existing entry, join an in-flight creation task, or register exactly one
    shared creation task. The slow ``adapter.start()`` I/O runs OUTSIDE the
    registry lock (in ``_create_adapter_task``), so a slow OpenCode startup on one
    session never blocks creation or requests for a different session. A cancelled
    waiter does NOT cancel the shared creation task for other waiters (awaiting a
    task never cancels it). On startup failure the partially created adapter is
    closed, the creation entry is removed, and a safe error propagates — leaving
    no broken session. The dispatch object is created before ``start`` and passed
    once; per-turn projectors bind to it while the session lock is held.

    If the session is currently closing/close_failed, raises a conflict error so
    the caller can return honest pre-stream 409/503 instead of spawning another
    process.
    """
    # 1) Under the registry lock: reuse, join, or register creation. NO I/O here.
    async with _sessions_lock:
        entry = _sessions.get(session_key)
        if entry is not None:
            if isinstance(entry, _ClosingMarker):
                raise RuntimeError(f"session {session_key} is closing")
            if entry.state == "closing":
                raise RuntimeError(f"session {session_key} is closing")
            if entry.state == "close_failed":
                raise RuntimeError(f"session {session_key} is in failed close state")
            if entry.state == "active":
                entry.touch()
                return entry.adapter  # type: ignore[return-value]
            # closed tombstone should not be in registry; recreate if present.
            if entry.state == "closed":
                _sessions.pop(session_key, None)
        existing = _creation_tasks.get(session_key)
        if existing is not None and not existing.done():
            wait_task = existing
        else:
            wait_task = asyncio.ensure_future(
                _create_adapter_task(session_key, factory, state, config)
            )
            _creation_tasks[session_key] = wait_task
            wait_task.add_done_callback(functools.partial(_on_creation_task_done, session_key))
            # Exact owner point: adapter/session creation REQUESTED (single-flight
            # registration). Lifecycle events enter the ONE central diagnostics hub
            # with safe scalar fields only — never a session/correlation id.
            with contextlib.suppress(Exception):
                get_diagnostics_hub().record(
                    EVENT["ADAPTER_CREATION_REQUESTED"],
                    "info",
                )

    # 2) Await the (possibly shared) creation task OUTSIDE the registry lock. The
    # shared task is shielded so cancellation of one waiter does not cancel creation
    # for other waiters; the cancelled caller still receives CancelledError.
    result = await asyncio.shield(wait_task)
    if result is _CREATION_ABORTED:
        # Controlled closing/shutdown — translate to safe session-closing response
        raise RuntimeError(f"session {session_key} is closing")
    if result is None:
        # Should not happen; treat as closing
        raise RuntimeError(f"session {session_key} creation aborted")
    return result  # type: ignore[return-value]


async def _create_adapter_task(
    session_key: str,
    factory: AgentAdapterFactory,
    state: Any | None,
    config: Any | None,
) -> AgentAdapter | None:
    """Single-flight adapter creation. All I/O happens OUTSIDE any registry lock.

    Returns the adapter on success, or the controlled sentinel _CREATION_ABORTED
    when the session was closed/shutdown while creation was in flight (not an
    exception, so no 'Task exception was never retrieved').
    Real startup failures still raise and propagate to active waiters.
    """
    adapter: AgentAdapter | None = None
    try:
        adapter = factory.create()
        # Per-session diagnostics VIEW of the ONE central hub (not a separate
        # recorder) linked to the adapter, the dispatch, and the session entry so
        # every prompt/tool/permission/lifecycle event lands in the ONE hub.
        rec = SessionDiagnosticsRecorder(short_id(session_key))
        # Session creation event into the central hub (single owner point:
        # "session created / adapter provisioning started"). No session/id field.
        with contextlib.suppress(Exception):
            rec.record(EVENT["SESSION_CREATED"], "info")
        # Link the session diagnostics recorder to the adapter so adapter-level
        # events (config option, prompt, permission response) are recorded.
        adapter.diag = rec
        dispatch = AssistantTransportDispatch()
        dispatch.diagnostics = rec
        cwd = _resolve_assistant_cwd(state, config)
        # Ensure cwd exists; create a temp fallback when needed.
        if not cwd.exists():
            import tempfile

            cwd = Path(tempfile.mkdtemp(prefix="rtai-assistant-"))

        # Slow startup I/O — must NOT hold _sessions_lock.
        await adapter.start(cwd, dispatch)
        # Exact owner point: safe child-process spawned status. No command line,
        # no PID, no argv — only the fixed token "spawned" and the short id.
        with contextlib.suppress(Exception):
            rec.record(EVENT["ADAPTER_SPAWNED"], "info", status="spawned")
        with contextlib.suppress(Exception):
            rec.record(EVENT["ADAPTER_READY"], "info")
    except BaseException:
        # Startup failed after spawn: ensure any owned child is torn down and no
        # broken session entry lingers.
        if "rec" in dir():
            with contextlib.suppress(Exception):
                rec.record(EVENT["ADAPTER_UNAVAILABLE"], "error")
        if adapter is not None:
            with contextlib.suppress(Exception):
                await adapter.close()
        async with _sessions_lock:
            # Remove only this task if it is still the current one
            cur = _creation_tasks.get(session_key)
            # Use identity check to avoid removing a newer task for same key
            if cur is not None and cur is asyncio.current_task():
                # This path is for the creation task itself; but _creation_tasks
                # holds the outer task, not current_task, so check by value?
                pass
            _creation_tasks.pop(session_key, None)
        raise

    entry = AssistantSessionEntry(adapter, dispatch)
    entry.diagnostics = rec
    entry.touch()
    close_outside = False
    abort_marker: _ClosingMarker | None = None
    async with _sessions_lock:
        tomb = _sessions.get(session_key)
        if (
            _shutting_down
            or isinstance(tomb, _ClosingMarker)
            or (tomb is not None and getattr(tomb, "state", None) == "closing")
        ):
            # Shutdown in progress, or the session was asked to close while this
            # creation was still in flight: do NOT register a live session.
            # Keep the closing marker while we close the new adapter outside the lock;
            # removal of the marker happens after close completes, under lock, so
            # new requests see 409 only while closure is genuinely active.
            # Retain exact marker object for identity check on removal.
            if isinstance(tomb, _ClosingMarker):
                abort_marker = tomb
            # Do not register; keep tombstone, just remove creation task
            _creation_tasks.pop(session_key, None)
            close_outside = True
        else:
            _sessions[session_key] = entry
            _creation_tasks.pop(session_key, None)
            close_outside = False
    if not close_outside:
        # Exact owner point: counts recorded right after the create transition
        # (entry registered as live). Bounded ints only.
        with contextlib.suppress(Exception):
            await _record_counts_event()
    if close_outside:
        # Close the adapter that was just started but should not be published
        with contextlib.suppress(Exception):
            await adapter.close()
        # Now that close has genuinely completed, remove the tombstone/marker so
        # the same key may be created again. This must be under lock and outside
        # the previous lock scope, and must check it is still the same exact marker.
        async with _sessions_lock:
            cur = _sessions.get(session_key)
            if abort_marker is not None and cur is abort_marker:
                _sessions.pop(session_key, None)
            # Also ensure creation task already removed (only if still this task)
            if _creation_tasks.get(session_key) is not None:
                # Only pop if no newer task has been registered for same key
                # The current task is already popped before, but keep safe
                _creation_tasks.pop(session_key, None)
        # Return controlled sentinel, not exception, so no unobserved Task exception
        with contextlib.suppress(Exception):
            await _record_counts_event()
        return _CREATION_ABORTED  # type: ignore[return-value]
    log_event(
        logger,
        logging.INFO,
        "assistant_session_created",
        session=short_id(session_key),
    )
    return adapter


def get_entry(session_key: str) -> AssistantSessionEntry | None:
    """Return the entry for *session_key* if it exists and is active."""
    entry = _sessions.get(session_key)
    if isinstance(entry, _ClosingMarker):
        return None
    if entry is not None and entry.state != "active":
        # For active path, closing entries are not considered available
        return None
    return entry  # type: ignore[return-value]


def get_entry_any(session_key: str) -> AssistantSessionEntry | _ClosingMarker | None:
    """Return entry regardless of state (for close/idle checks)."""
    return _sessions.get(session_key)


async def close_session(session_id: str) -> bool:
    """Remove and close the session identified by ``session_id``.

    Returns False if the session does not exist or already successfully closed.
    The registry lock is released before any await (creation task, close task, or
    adapter I/O). Close is idempotent and concurrently safe via a shared close
    task. Tombstone retained on failure. If a creation is still in flight, we await
    it outside the lock and then close the now-materialized entry, so idle cleanup
    / shutdown cannot leave a half-created adapter.
    """
    pending_creation: asyncio.Task[AgentAdapter | None] | None = None
    pending_marker: _ClosingMarker | None = None
    close_wait: asyncio.Task[bool] | None = None
    entry: Any = None
    async with _sessions_lock:
        entry = _sessions.get(session_id)
        if isinstance(entry, _ClosingMarker):
            # Creation was aborted during close: nothing live to close.
            # Keep marker until creation task finishes and removes it; treat as closing
            return False
        if entry is None:
            creation = _creation_tasks.get(session_id)
            if creation is None or creation.done():
                return False
            # Creation in flight: tombstone the key under the lock so a concurrent
            # new request (get_or_create_adapter / pre-stream check) sees a closing
            # session and does NOT start another adapter. Released under the lock,
            # then awaited outside. Retain exact marker for identity check.
            pending_marker = _ClosingMarker()
            _sessions[session_id] = pending_marker
            pending_creation = creation
            # Store exact marker for later identity check (avoid blind pop)
            # Use a local variable captured by the pending_creation handling below
            # We attach it to the pending_creation task for later retrieval
            with contextlib.suppress(Exception):
                pending_creation._close_marker = pending_marker  # type: ignore[attr-defined]
        elif entry.state == "closed":
            _sessions.pop(session_id, None)
            return False
        elif entry.state == "closing" and entry.close_task is not None:
            # Concurrent close: await same task outside lock
            close_wait = entry.close_task
        elif entry.state == "closing":
            # Should not happen without task, but treat as closing
            return False
        elif entry.state == "close_failed":
            # Retain tombstone, allow cleanup_all to retry
            return False
        else:  # active
            entry.state = "closing"
            with contextlib.suppress(Exception):
                if entry.diagnostics is not None:
                    entry.diagnostics.record(EVENT["SESSION_CLOSING"], "info")

            # Create shared close task
            async def _do_close() -> bool:
                # Outside registry lock: request cancel if active, allow turn to finish
                if entry.lock.locked():
                    try:
                        await entry.adapter.cancel()
                    except Exception as exc:
                        log_event(
                            logger,
                            logging.WARNING,
                            "assistant_session_cancel_failed",
                            session=short_id(session_id),
                            error=type(exc).__name__,
                        )
                    # Allow active run to execute its finally (unbind + release lock).
                    # Wait for the turn lock to be released, then release it. Lock
                    # order here is entry.lock first; the permission_lock below is
                    # taken afterward and released first (reverse order).
                    await entry.lock.acquire()
                    entry.lock.release()
                # Coordinate cleanup with in-flight permission responses using the same
                # dedicated permission lock the response endpoint holds, so clearing
                # cannot run between adapter acceptance and registry/projection.
                async with entry.permission_lock:
                    entry.dispatch.clear()
                    entry.dispatch.clear_permissions()
                try:
                    await entry.adapter.close()
                except Exception as exc:
                    log_event(
                        logger,
                        logging.ERROR,
                        "assistant_session_close_failed",
                        session=short_id(session_id),
                        error=type(exc).__name__,
                    )
                    raise
                # Exact owner point: safe child-process exited status after the
                # owned adapter close completed. No command line, no PID.
                with contextlib.suppress(Exception):
                    get_diagnostics_hub().record(
                        EVENT["ADAPTER_EXITED"],
                        "info",
                        status="exited",
                    )
                return True

            close_wait = asyncio.create_task(_do_close())
            entry.close_task = close_wait

    # If a creation was in flight, let it finish (outside lock), then close it.
    # The shared task is shielded so a cancelled close caller does not cancel the
    # creation; the cancelled caller still receives CancelledError.
    if pending_creation is not None:
        try:
            await asyncio.shield(pending_creation)
        except asyncio.CancelledError:
            # Caller cancelled, but creation continues and will remove its marker
            raise
        except Exception:
            pass
        # Now the creation task has finished (either returned entry or sentinel).
        # Use exact marker identity to avoid removing a newer marker for same key.
        async with _sessions_lock:
            cur = _sessions.get(session_id)
            if cur is pending_marker:
                _sessions.pop(session_id, None)
                _creation_tasks.pop(session_id, None)
        return True

    # Outside registry lock: await close task
    assert close_wait is not None
    try:
        result = await asyncio.shield(close_wait)
    except asyncio.CancelledError:
        # Cancelled caller receives CancelledError; shared task continues
        raise
    except Exception as exc:
        # Failure: retain tombstone as close_failed
        async with _sessions_lock:
            e = _sessions.get(session_id)
            if e is not None and e is entry:
                e.state = "close_failed"
                e.close_error = type(exc).__name__
                e.close_task = None
                log_event(
                    logger,
                    logging.ERROR,
                    "assistant_session_close_failed_tombstone",
                    session=short_id(session_id),
                    error=type(exc).__name__,
                )
        raise
    else:
        # Success: remove tombstone under lock
        async with _sessions_lock:
            e = _sessions.get(session_id)
            if e is not None and e is entry and e.state == "closing":
                _sessions.pop(session_id, None)
                e.state = "closed"
                e.close_task = None
                log_event(
                    logger, logging.INFO, "assistant_session_closed", session=short_id(session_id)
                )
        # Exact owner point: counts recorded right after the close transition
        # (tombstone removed). Bounded ints only.
        with contextlib.suppress(Exception):
            await _record_counts_event()
        return result


async def cleanup_all() -> None:
    """Close all managed adapters.  Called on application shutdown."""
    # Snapshot under lock, then clear. Mark shutting_down so in-flight creations
    # tear down instead of registering a live session that we would otherwise leak.
    async with _sessions_lock:
        global _shutting_down
        _shutting_down = True
        entries = [e for e in _sessions.values() if isinstance(e, AssistantSessionEntry)]
        creations = list(_creation_tasks.values())
        _sessions.clear()
        _creation_tasks.clear()
    # Await in-flight creations first (they self-close when _shutting_down is set).
    # Every wait on a task stored in _creation_tasks must use shield, including shutdown.
    for ctask in creations:
        try:
            await asyncio.shield(ctask)
        except asyncio.CancelledError:
            # Cancelling cleanup must not propagate into shared creation
            pass
        except Exception:
            pass
    for entry in entries:
        # If entry was closing with a task, await it; else close directly.
        if entry.close_task is not None and not entry.close_task.done():
            try:
                await asyncio.shield(entry.close_task)
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        # Ensure final close (idempotent).
        with contextlib.suppress(Exception):
            await entry.close()
        entry.state = "closed"
    async with _sessions_lock:
        _shutting_down = False
    # Exact owner point: counts after the shutdown close transition. Must run
    # outside the registry lock - _record_counts_event acquires it itself.
    with contextlib.suppress(Exception):
        await _record_counts_event()
    log_event(logger, logging.INFO, "assistant_sessions_cleaned")


async def _idle_cleanup_loop() -> None:
    """Periodic loop that expires idle sessions."""
    timeout = _idle_timeout_seconds()
    while True:
        try:
            await asyncio.sleep(IDLE_CHECK_INTERVAL_SECONDS)
            # Refresh timeout each iteration (env may change in tests)
            timeout = _idle_timeout_seconds()
            now = time.monotonic()
            expired: list[str] = []
            async with _sessions_lock:
                for sid, entry in list(_sessions.items()):
                    # Skip transient close tombstones; never expire while turn lock is
                    # held (prompt active) or while closing.
                    if not isinstance(entry, AssistantSessionEntry):
                        continue
                    if entry.lock.locked():
                        continue
                    if entry.state != "active":
                        continue
                    if entry._closed:
                        continue
                    if now - entry.last_activity > timeout:
                        expired.append(sid)
            if expired:
                # Distinct, safe observability event for idle cleanup closure.
                # Only status/reason/counts — never a session id, path, prompt,
                # model, tool data, exception, or secret.
                with contextlib.suppress(Exception):
                    get_diagnostics_hub().record(
                        EVENT["SESSION_IDLE_EXPIRED"],
                        "info",
                        reason="idle_timeout",
                        expiredCount=len(expired),
                    )
            for sid in expired:
                log_event(
                    logger, logging.INFO, "assistant_session_idle_expired", session=short_id(sid)
                )
                with contextlib.suppress(Exception):  # Leave tombstone for shutdown retry
                    await close_session(sid)
        except asyncio.CancelledError:
            break
        except Exception:
            # Do not let loop die on unexpected error
            await asyncio.sleep(IDLE_CHECK_INTERVAL_SECONDS)


async def start_idle_cleanup() -> None:
    global _idle_task
    if _idle_task is not None and not _idle_task.done():
        return
    _idle_task = asyncio.create_task(_idle_cleanup_loop())


async def stop_idle_cleanup() -> None:
    global _idle_task
    task = _idle_task
    _idle_task = None
    if task is not None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
