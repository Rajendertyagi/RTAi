"""Agent adapter boundary.

Application code and the frontend depend on this module -
never on a concrete adapter or on the ACP SDK. Concrete adapters (currently
OpenCode) translate between their provider and the normalized protocol; they
also own the single child process they spawned via :class:`OwnedProcess`.

Runtime discovery of capabilities is the NEXT phase (2A-B). This phase only
establishes the interface, the capability domain models and safe process
ownership.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from .prompt_content import PromptContent

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
    async def submit_prompt_content(self, content: list[PromptContent]) -> None:
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

    async def respond_to_permission(self, permission_request_id: str, option_id: str) -> bool:
        """Resolve a pending permission/HITL request with the user's choice.

        Returns ``True`` when the permission was found and resolved, ``False``
        otherwise. Adapters that do not implement interactive (HITL) permissions
        return ``False`` so the transport endpoint can surface an explicit 501
        instead of guessing. This is the permanent public contract - callers
        must not reach into adapter internals to resolve permissions.
        """
        return False

    def owned_process(self) -> OwnedProcess | None:
        """The exact child this adapter spawned, if one exists."""
        return None

    async def select(self, kind: SelectionKind, value_id: str) -> SelectionResult:
        raise NotImplementedError("Capability selection arrives in Phase 2A-B.")
