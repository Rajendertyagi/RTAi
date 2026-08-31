"""Suggestions pipeline for ACP-based agent adapters.

Defines the event bus and abstract evaluator interface that allows a later
phase to generate contextual follow-up prompts after a turn completes.
The current implementation is a no-op stub so the extension point exists
without affecting the live stream.

Design decisions:
- The bus is attached to the adapter (not the route) so each adapter owns
  its own listener lifecycle. The route injects the evaluator at startup.
- ``fire_on_turn_completed`` is called after the ``done`` event has been
  emitted — the turn is terminal, so no further streaming events can race
  against the suggestion work.
- The bus is async-first: listeners run in the background via
  ``asyncio.create_task`` and errors are caught silently so a broken
  evaluator cannot stall the main stream.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TurnContext:
    """Immutable snapshot of the turn that just completed.

    Carried from the adapter into the suggestion evaluator so the worker
    has everything it needs without reaching back into adapter state.
    """

    session_id: str
    turn_id: str
    message_id: str
    user_text: str
    agent_name: str
    tool_call_count: int
    part_kinds: list[str] = field(default_factory=list)


class AbstractSuggestionEvaluator(ABC):
    """Hook for post-turn suggestion generation.

    Subclasses implement ``evaluate`` to return one or more suggested
    follow-up prompts. The base class provides a no-op stub so the event
    bus works without wiring anything in yet.
    """

    @abstractmethod
    async def evaluate(self, ctx: TurnContext) -> list[str]:
        """Return 0-N suggestion strings for the given turn context."""
        ...


class NoOpSuggestionEvaluator(AbstractSuggestionEvaluator):
    """Default stub: emits no suggestions."""

    async def evaluate(self, ctx: TurnContext) -> list[str]:
        return []


class SuggestionEventBus:
    """Async fire-and-forget bus for turn-completion events.

    The adapter calls ``fire_on_turn_completed`` at the end of a turn. The
    bus looks up the registered evaluator, runs it asynchronously, and
    never lets an exception propagate back to the stream path.
    """

    def __init__(self, evaluator: AbstractSuggestionEvaluator | None = None) -> None:
        self._evaluator = evaluator or NoOpSuggestionEvaluator()

    def set_evaluator(self, evaluator: AbstractSuggestionEvaluator) -> None:
        """Replace the active evaluator at runtime (useful in tests)."""
        self._evaluator = evaluator

    def fire_on_turn_completed(self, ctx: TurnContext) -> None:
        """Schedule non-blocking suggestion evaluation.

        Errors are logged but never propagated; the main stream is
        unaffected by a failing evaluator.
        """
        if ctx.user_text.strip() == "":
            return

        async def _run() -> None:
            try:
                suggestions = await self._evaluator.evaluate(ctx)
                if suggestions:
                    logger.debug(
                        "suggestions_emitted",
                        turn_id=ctx.turn_id,
                        count=len(suggestions),
                    )
            except Exception:
                logger.exception("suggestion_evaluation_failed")

        asyncio.get_running_loop().create_task(_run())
