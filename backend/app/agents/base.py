"""Agent adapter boundary.

Application code, the WebSocket layer and the frontend depend on this module -
never on a concrete adapter or on the ACP SDK. Concrete adapters (currently
OpenCode) translate between their provider and the normalized protocol; they
also own the single child process they spawned via :class:`OwnedProcess`.

Runtime discovery of capabilities is the NEXT phase (2A-B). This phase only
establishes the interface, the capability domain models and safe process
ownership.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .capabilities import CapabilitySnapshot
from .owned_process import OwnedProcess

Emit = Callable[[dict[str, Any]], Awaitable[None]]

SelectionKind = Literal["model", "mode", "thinking", "agent"]


@dataclass(frozen=True)
class SelectionResult:
    """Outcome placeholder for the Phase 2A-B selection extension point."""

    kind: SelectionKind
    applied: bool
    message: str = ""


class AgentAdapter(ABC):
    """Lifecycle + introspection contract every agent backend implements."""

    @abstractmethod
    async def start(self, cwd: Path, emit: Emit) -> None:
        """Spawn/connect to the agent process and open the initial session."""

    @abstractmethod
    def capability_snapshot(self) -> CapabilitySnapshot:
        """Return what this adapter discovered, without inventing data."""

    @abstractmethod
    async def submit_prompt(self, text: str) -> None:
        """Send one user prompt; results arrive through the emit sink."""

    @abstractmethod
    async def cancel(self) -> None:
        """Cancel the in-flight generation, if any."""

    @abstractmethod
    async def close(self) -> None:
        """Tear down the session and the owned agent process."""

    def owned_process(self) -> OwnedProcess | None:
        """The exact child this adapter spawned, if one exists."""
        return None

    # ------------------------------------------------------------------
    # Extension points - implemented in Phase 2A-B (runtime discovery and
    # selection). Deliberately unimplemented here so no phase pretends to
    # support something the adapter does not actually do yet.
    # ------------------------------------------------------------------

    async def select(self, kind: SelectionKind, value_id: str) -> SelectionResult:
        raise NotImplementedError("Capability selection arrives in Phase 2A-B.")

    async def refresh_capabilities(self) -> CapabilitySnapshot:
        raise NotImplementedError("Live capability refresh arrives in Phase 2A-B.")


async def finish_prompt(adapter: AgentAdapter, text: str, emit: Emit) -> None:
    """Drive one prompt turn to its normalized terminal event."""
    try:
        await adapter.submit_prompt(text)
        await emit({"type": "done"})
    except asyncio.CancelledError:
        await emit({"type": "done", "reason": "cancelled"})
        raise
    except Exception as exc:
        await emit({"type": "error", "message": str(exc)})
