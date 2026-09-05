"""Factory injection wiring plus prompt/cancel behavior compatibility.

Uses a FakeAdapter through the real ``create_app``/``finish_prompt`` seams.
No WebSocket server is started and no OpenCode binary is involved.
"""

from __future__ import annotations

import asyncio
import unittest
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from app.agents.base import AgentAdapter, Emit, finish_prompt
from app.agents.capabilities import CapabilitySnapshot
from app.agents.factory import OpenCodeAdapterFactory
from app.main import create_app


class FakeAdapter(AgentAdapter):
    def __init__(self, prompt_behavior: str = "ok") -> None:
        self.prompt_behavior = prompt_behavior
        self.started = False
        self.closed = False
        self.cancelled = False
        self.prompts: list[str] = []

    async def start(self, cwd: Path, emit: Emit) -> None:
        self.started = True

    def capability_snapshot(self) -> CapabilitySnapshot:
        return CapabilitySnapshot(source="fake")

    async def submit_prompt(self, text: str, turn_id: str = "", message_id: str = "") -> None:
        self.prompts.append(text)
        if self.prompt_behavior == "explode":
            raise RuntimeError("provider exploded")

    async def submit_prompt_content(
        self, content: list[Any], turn_id: str = "", message_id: str = ""
    ) -> None:
        pass

    async def cancel(self) -> None:
        self.cancelled = True

    async def close(self) -> None:
        self.closed = True


class FakeAdapterFactory:
    def __init__(self) -> None:
        self.created: list[FakeAdapter] = []

    def create(self) -> AgentAdapter:
        adapter = FakeAdapter()
        self.created.append(adapter)
        return adapter


class FactoryWiringTests(unittest.TestCase):
    def test_default_factory_is_opencode(self) -> None:
        app = create_app()
        factory = app.state.adapter_factory
        self.assertIsInstance(factory, OpenCodeAdapterFactory)

    def test_injected_factory_is_used_verbatim(self) -> None:
        fake_factory = FakeAdapterFactory()
        app = create_app(adapter_factory=fake_factory)  # type: ignore[arg-type]
        stored = app.state.adapter_factory
        self.assertIs(stored, fake_factory)
        # The routes obtain adapters exclusively from this factory.
        adapter_one = stored.create()
        adapter_two = stored.create()
        self.assertIsNot(adapter_one, adapter_two)
        self.assertEqual(len(fake_factory.created), 2)


class FinishPromptCompatTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.adapter = FakeAdapter()
        self.emitted: list[dict[str, Any]] = []

        async def sink(event: dict[str, Any]) -> None:
            self.emitted.append(event)

        self.emit: Callable[[dict[str, Any]], Awaitable[None]] = sink

    async def test_success_emits_done(self) -> None:
        await finish_prompt(self.adapter, "hello", self.emit)
        self.assertEqual([e["type"] for e in self.emitted], ["done"])
        self.assertEqual(self.adapter.prompts, ["hello"])

    async def test_provider_error_emits_error_event(self) -> None:
        self.adapter.prompt_behavior = "explode"
        await finish_prompt(self.adapter, "boom", self.emit)
        self.assertEqual(self.emitted[-1]["type"], "error")
        self.assertIn("exploded", str(self.emitted[-1].get("message")))

    async def test_cancellation_emits_cancelled_and_reraises(self) -> None:
        class CancelledAdapter(FakeAdapter):
            async def submit_prompt(
                self, text: str, turn_id: str = "", message_id: str = ""
            ) -> None:
                self.prompts.append(text)
                raise asyncio.CancelledError()

        adapter = CancelledAdapter()
        with self.assertRaises(asyncio.CancelledError):
            await finish_prompt(adapter, "slow", self.emit)
        self.assertEqual([e["type"] for e in self.emitted], ["done"])
        self.assertEqual(self.emitted[0].get("reason"), "cancelled")


if __name__ == "__main__":
    unittest.main()
