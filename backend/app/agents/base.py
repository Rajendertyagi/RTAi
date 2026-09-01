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
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from .acp.prompt_content import PromptContent

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

    async def submit_prompt(self, text: str, turn_id: str = "", message_id: str = "") -> None:
        """Send one user prompt; results arrive through the emit sink."""

    async def submit_prompt_content(
        self, content: list[PromptContent], turn_id: str = "", message_id: str = ""
    ) -> None:
        """Send a multi-block prompt with validated attachments.

        Adapters that cannot accept attachments should raise a clear error;
        callers gate on the advertised attachment capabilities first.
        """

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
    # Suggestions pipeline — injected by the WebSocket route after adapter
    # creation. Adapters that support it call fire_suggestions() at the end
    # of each turn; the bus runs the registered evaluator in the background.
    # ------------------------------------------------------------------

    def set_suggestions_evaluator(self, evaluator: Any) -> None:
        """Inject a :class:`AbstractSuggestionEvaluator` at runtime.

        The default no-op implementation means servers that do not yet use
        the suggestions pipeline (e.g. the HTTP+SSE adapter) remain
        unaffected. AcpSession overrides this to wire the bus.
        """

    def fire_suggestions(
        self, user_text: str = "", turn_id: str = "", message_id: str = ""
    ) -> None:
        """Signal that the current turn has completed.

        The default no-op means adapters that do not support the pipeline
        remain unaffected. AcpSession overrides this to delegate to the bus.
        """

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
