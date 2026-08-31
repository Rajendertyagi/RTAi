"""Ownership wrapper for the one agent process RTAi itself spawned (ADR-0006).

An ``OwnedProcess`` is created only from the handle returned by the adapter's
own spawn call. Cleanup operates exclusively through that stored handle:

1. Cooperative shutdown first (the SDK context-manager / connection close).
2. Forced kill of the stored handle only if cooperative shutdown does not
   finish within ``force_timeout_seconds``.

There is deliberately no API here for enumerating processes, matching by name,
or acting on any PID other than the stored handle. ``close`` is idempotent.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable, Sequence
from enum import Enum
from typing import Any

from ..logging_config import log_event

logger = logging.getLogger(__name__)


class OwnershipState(str, Enum):
    RUNNING = "running"
    CLOSING = "closing"
    CLOSED = "closed"
    FAILED = "failed"


DEFAULT_FORCE_TIMEOUT_SECONDS = 5.0


class OwnedProcess:
    def __init__(
        self,
        *,
        handle: Any,
        pid: int | None,
        argv: Sequence[str],
        cooperative_close: Callable[[], Awaitable[None]],
        force_timeout_seconds: float = DEFAULT_FORCE_TIMEOUT_SECONDS,
    ) -> None:
        self._handle = handle
        self._pid = pid
        self._argv = tuple(argv)
        self._cooperative_close = cooperative_close
        self._force_timeout_seconds = force_timeout_seconds
        self._state = OwnershipState.RUNNING
        self.session_id: str | None = None
        self.last_close_error: str | None = None

    @property
    def state(self) -> OwnershipState:
        return self._state

    @property
    def pid(self) -> int | None:
        return self._pid

    @property
    def argv(self) -> tuple[str, ...]:
        return self._argv

    def attach_session(self, session_id: str) -> None:
        """Record the ACP session created on this process (never another's)."""
        if self._state is OwnershipState.RUNNING:
            self.session_id = session_id

    async def close(self) -> OwnershipState:
        """Cooperative-first, idempotent shutdown of exactly this owned child."""
        if self._state is not OwnershipState.RUNNING:
            return self._state
        self._state = OwnershipState.CLOSING
        self.last_close_error = None
        log_event(logger, logging.DEBUG, "owned_process_closing", pid=self._pid)
        try:
            await asyncio.wait_for(self._cooperative_close(), self._force_timeout_seconds)
        except asyncio.TimeoutError:
            self.last_close_error = f"cooperative close exceeded {self._force_timeout_seconds}s"
            log_event(
                logger,
                logging.ERROR,
                "owned_process_close_failed",
                pid=self._pid,
                reason="cooperative_timeout",
            )
            self._force_kill()
        except Exception as exc:  # defensive: cleanup must stay total
            self.last_close_error = str(exc)
            log_event(
                logger,
                logging.ERROR,
                "owned_process_close_failed",
                pid=self._pid,
                reason=type(exc).__name__,
            )
            self._force_kill()
        self._state = OwnershipState.CLOSED
        log_event(
            logger,
            logging.INFO,
            "owned_process_closed",
            pid=self._pid,
            state=self._state.value,
        )
        return self._state

    def mark_start_failed(self) -> None:
        """Startup never completed; the wrapper refuses further lifecycle use."""
        if self._state is OwnershipState.RUNNING:
            self._state = OwnershipState.FAILED
            log_event(
                logger,
                logging.INFO,
                "owned_process_start_failed",
                pid=self._pid,
            )

    def _force_kill(self) -> None:
        """Last-resort termination aimed solely at the stored handle."""
        log_event(logger, logging.WARNING, "owned_process_force_kill", pid=self._pid)
        kill = getattr(self._handle, "kill", None)
        if callable(kill):
            result = kill()
            if inspect.isawaitable(result):
                # Real asyncio subprocesses expose a synchronous kill(); await
                # defensively in case a provider handle differs.
                asyncio.ensure_future(result)
