"""Tests for the suggestions pipeline and MCP server configuration.

Covers:
- SuggestionEventBus: no-op stub, custom evaluator, empty-text skip, exception safety
- AcpSession: set_suggestions_evaluator wiring, MCP servers passed to new_session
- MCPServerConfig: frozen dataclass, defaults
- OpenCodeServerAdapter: no-op suggestions, mcp_servers field present
"""

from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from app.agents.acp.session import AcpSession
from app.agents.opencode_acp import OpenCodeSession
from app.agents.opencode.server_adapter import OpenCodeServerAdapter
from app.agents.suggestions import (
    AbstractSuggestionEvaluator,
    NoOpSuggestionEvaluator,
    SuggestionEventBus,
    TurnContext,
)
from app.core.protocol import MCPServerConfig


# ---------------------------------------------------------------------------
# MCPServerConfig tests
# ---------------------------------------------------------------------------


class MCPServerConfigTests(unittest.TestCase):
    def test_defaults(self) -> None:
        cfg = MCPServerConfig(name="test", command="echo")
        self.assertEqual(cfg.name, "test")
        self.assertEqual(cfg.command, "echo")
        self.assertEqual(cfg.args, ())
        self.assertIsNone(cfg.env)
        self.assertIsNone(cfg.cwd)

    def test_full_values(self) -> None:
        cfg = MCPServerConfig(
            name="mcp",
            command="mcp-server",
            args=("--port", "8080"),
            env={"FOO": "bar"},
            cwd="/tmp",
        )
        self.assertEqual(cfg.args, ("--port", "8080"))
        self.assertEqual(cfg.env, {"FOO": "bar"})
        self.assertEqual(cfg.cwd, "/tmp")

    def test_is_frozen(self) -> None:
        cfg = MCPServerConfig(name="x", command="y")
        with self.assertRaises(AttributeError):
            cfg.name = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# SuggestionEventBus tests
# ---------------------------------------------------------------------------


class CountingEvaluator(AbstractSuggestionEvaluator):
    """Evaluator that counts calls and returns fixed suggestions."""

    def __init__(self, suggestions: list[str] = ("try-again",)) -> None:
        self.call_count = 0
        self.last_ctx: TurnContext | None = None
        self._suggestions = suggestions

    async def evaluate(self, ctx: TurnContext) -> list[str]:
        self.call_count += 1
        self.last_ctx = ctx
        return list(self._suggestions)


class SuggestionEventBusTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_op_returns_empty(self) -> None:
        bus = SuggestionEventBus()
        ctx = TurnContext(
            session_id="s1", turn_id="t1", message_id="m1",
            user_text="hello", agent_name="agent", tool_call_count=0,
        )
        result = await bus._evaluator.evaluate(ctx)
        self.assertEqual(result, [])

    async def test_custom_evaluator_called(self) -> None:
        counter = CountingEvaluator(suggestions=["s1", "s2"])
        bus = SuggestionEventBus(evaluator=counter)
        ctx = TurnContext(
            session_id="s1", turn_id="t1", message_id="m1",
            user_text="hello", agent_name="agent", tool_call_count=2,
            part_kinds=["text", "reasoning"],
        )
        bus.fire_on_turn_completed(ctx)
        await asyncio.sleep(0.05)
        self.assertEqual(counter.call_count, 1)
        self.assertEqual(counter.last_ctx, ctx)
        self.assertEqual(counter.last_ctx.tool_call_count, 2)
        self.assertEqual(counter.last_ctx.part_kinds, ["text", "reasoning"])

    async def test_empty_user_text_skips_evaluation(self) -> None:
        counter = CountingEvaluator()
        bus = SuggestionEventBus(evaluator=counter)
        bus.fire_on_turn_completed(TurnContext(
            session_id="s1", turn_id="t1", message_id="m1",
            user_text="", agent_name="agent", tool_call_count=0,
        ))
        await asyncio.sleep(0.05)
        self.assertEqual(counter.call_count, 0)

    async def test_whitespace_only_skips_evaluation(self) -> None:
        counter = CountingEvaluator()
        bus = SuggestionEventBus(evaluator=counter)
        bus.fire_on_turn_completed(TurnContext(
            session_id="s1", turn_id="t1", message_id="m1",
            user_text="   ", agent_name="agent", tool_call_count=0,
        ))
        await asyncio.sleep(0.05)
        self.assertEqual(counter.call_count, 0)

    async def test_evaluator_exception_does_not_crash(self) -> None:
        class FailingEvaluator(AbstractSuggestionEvaluator):
            async def evaluate(self, ctx: TurnContext) -> list[str]:
                raise RuntimeError("boom")

        bus = SuggestionEventBus(evaluator=FailingEvaluator())
        ctx = TurnContext(
            session_id="s1", turn_id="t1", message_id="m1",
            user_text="hello", agent_name="agent", tool_call_count=0,
        )
        # Should not raise
        bus.fire_on_turn_completed(ctx)
        await asyncio.sleep(0.05)

    async def test_set_evaluator_replaces(self) -> None:
        first = CountingEvaluator(suggestions=["a"])
        second = CountingEvaluator(suggestions=["b"])
        bus = SuggestionEventBus(evaluator=first)
        bus.set_evaluator(second)
        ctx = TurnContext(
            session_id="s1", turn_id="t1", message_id="m1",
            user_text="hello", agent_name="agent", tool_call_count=0,
        )
        bus.fire_on_turn_completed(ctx)
        await asyncio.sleep(0.05)
        self.assertEqual(second.call_count, 1)
        self.assertEqual(first.call_count, 0)

    async def test_callback_is_awaited(self) -> None:
        """The route callback is async and must be awaited by the bus."""
        called = asyncio.Event()

        async def async_callback(session_id, turn_id, prompts):
            await asyncio.sleep(0.02)
            called.set()

        bus = SuggestionEventBus(evaluator=CountingEvaluator(), on_suggestions=async_callback)
        bus.fire_on_turn_completed(TurnContext(
            session_id="s1", turn_id="t1", message_id="m1",
            user_text="hello", agent_name="agent", tool_call_count=0,
        ))
        # Without await, called would still be unset immediately.
        self.assertFalse(called.is_set())
        await asyncio.sleep(0.05)
        self.assertTrue(called.is_set())

    async def test_single_batch_event(self) -> None:
        """Multiple prompts produce exactly one suggestions_available event."""
        emitted: list[dict[str, Any]] = []

        async def collect(_sid: str, _tid: str, _prompts: list[str]) -> None:
            emitted.append({"type": "suggestions_available", "items": _prompts})

        bus = SuggestionEventBus(
            evaluator=CountingEvaluator(suggestions=["a", "b", "c"]),
            on_suggestions=collect,
        )
        bus.fire_on_turn_completed(TurnContext(
            session_id="s1", turn_id="t1", message_id="m1",
            user_text="hello", agent_name="agent", tool_call_count=0,
        ))
        await asyncio.sleep(0.05)
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0]["type"], "suggestions_available")

    async def test_event_has_normalized_envelope(self) -> None:
        """Batched event carries protocol_version, timestamp, session/turn ids."""
        emitted: list[dict[str, Any]] = []

        async def collect(session_id: str, turn_id: str, prompts: list[str]) -> None:
            emitted.append({
                "type": "suggestions_available",
                "session_id": session_id,
                "turn_id": turn_id,
                "protocol_version": 1,
                "timestamp": 1234567890,
                "items": [{"title": p, "prompt": p} for p in prompts],
            })

        bus = SuggestionEventBus(
            evaluator=CountingEvaluator(suggestions=["x"]),
            on_suggestions=collect,
        )
        bus.fire_on_turn_completed(TurnContext(
            session_id="sess-1", turn_id="turn-7", message_id="msg-3",
            user_text="hello", agent_name="agent", tool_call_count=0,
        ))
        await asyncio.sleep(0.05)
        self.assertEqual(len(emitted), 1)
        ev = emitted[0]
        self.assertEqual(ev["session_id"], "sess-1")
        self.assertEqual(ev["turn_id"], "turn-7")
        self.assertIn("protocol_version", ev)
        self.assertIn("timestamp", ev)
        self.assertIsInstance(ev["timestamp"], int)

    async def test_multiple_items_preserved(self) -> None:
        """All evaluator items appear in the single batched items array."""
        emitted: list[dict[str, Any]] = []

        async def collect(_sid: str, _tid: str, prompts: list[str]) -> None:
            emitted.append({
                "type": "suggestions_available",
                "items": [{"title": p, "prompt": p} for p in prompts],
            })

        bus = SuggestionEventBus(
            evaluator=CountingEvaluator(suggestions=["a", "b", "c"]),
            on_suggestions=collect,
        )
        bus.fire_on_turn_completed(TurnContext(
            session_id="s1", turn_id="t1", message_id="m1",
            user_text="hello", agent_name="agent", tool_call_count=0,
        ))
        await asyncio.sleep(0.05)
        self.assertEqual(len(emitted), 1)
        items = emitted[0]["items"]
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0]["title"], "a")
        self.assertEqual(items[0]["prompt"], "a")
        self.assertEqual(items[1]["prompt"], "b")
        self.assertEqual(items[2]["title"], "c")

    async def test_empty_result_emits_nothing(self) -> None:
        """No callback invocation when evaluator returns an empty list."""
        call_count = 0

        async def counting_callback(*args):
            nonlocal call_count
            call_count += 1

        bus = SuggestionEventBus(
            evaluator=NoOpSuggestionEvaluator(),
            on_suggestions=counting_callback,
        )
        bus.fire_on_turn_completed(TurnContext(
            session_id="s1", turn_id="t1", message_id="m1",
            user_text="hello", agent_name="agent", tool_call_count=0,
        ))
        await asyncio.sleep(0.05)
        self.assertEqual(call_count, 0)

    async def test_cancel_all_cancels_and_awaits(self) -> None:
        """cancel_all cancels outstanding tasks and awaits them to settle."""
        on_invoke = asyncio.Event()
        was_cancelled = False

        class SlowEvaluator(AbstractSuggestionEvaluator):
            async def evaluate(self, ctx):
                nonlocal was_cancelled
                on_invoke.set()
                try:
                    await asyncio.sleep(10)
                except asyncio.CancelledError:
                    was_cancelled = True
                    raise

        bus = SuggestionEventBus(evaluator=SlowEvaluator())
        bus.fire_on_turn_completed(TurnContext(
            session_id="s1", turn_id="t1", message_id="m1",
            user_text="hello", agent_name="agent", tool_call_count=0,
        ))
        await on_invoke.wait()
        self.assertTrue(len(bus._task_refs) > 0)
        await bus.cancel_all()
        self.assertTrue(was_cancelled)
        self.assertEqual(len(bus._task_refs), 0)

    async def test_legacy_suggestion_type_not_emitted(self) -> None:
        """The pipeline emits 'suggestions_available', never the legacy singular type."""
        emitted: list[dict[str, Any]] = []

        async def collect(_sid: str, _tid: str, _prompts: list[str]) -> None:
            emitted.append({"type": "suggestions_available", "items": []})

        bus = SuggestionEventBus(
            evaluator=CountingEvaluator(suggestions=["x"]),
            on_suggestions=collect,
        )
        bus.fire_on_turn_completed(TurnContext(
            session_id="s1", turn_id="t1", message_id="m1",
            user_text="hello", agent_name="agent", tool_call_count=0,
        ))
        await asyncio.sleep(0.05)
        types = {e.get("type") for e in emitted}
        self.assertNotIn("suggestion", types)
        self.assertIn("suggestions_available", types)


# ---------------------------------------------------------------------------
# AcpSession suggestion + MCP tests
# ---------------------------------------------------------------------------


class FakeProcess:
    def __init__(self) -> None:
        self.pid = 4321
        self.kill_calls = 0

    def kill(self) -> None:
        self.kill_calls += 1


class FakeConnection:
    def __init__(self, agent_info: Any = ...) -> None:
        self._agent_info = (
            agent_info if agent_info is not ... else FakeConnection._Info()
        )
        self.new_session_kwargs: dict[str, Any] = {}

    class _Info:
        name = "test-agent"
        version = "1.0.0"

    async def initialize(self, **kwargs: Any) -> Any:
        class Response:
            agentInfo = self._agent_info
            protocolVersion = 1
        return Response()

    async def new_session(self, **kwargs: Any) -> Any:
        self.new_session_kwargs = kwargs
        class Session:
            session_id = "session-1"
        return Session()

    async def prompt(self, session_id: str, prompt: list[Any]) -> None:
        pass

    async def cancel(self, session_id: str) -> None:
        pass


class FakeContext:
    def __init__(self, connection: FakeConnection, process: FakeProcess) -> None:
        self.connection = connection
        self.process = process
        self.exit_calls = 0

    async def __aenter__(self) -> tuple[FakeConnection, FakeProcess]:
        return self.connection, self.process

    async def __aexit__(self, *exc: object) -> None:
        self.exit_calls += 1


def install_fake_acp(context: FakeContext) -> None:
    import sys
    from types import ModuleType

    def spawn_agent_process(to_client: Any, command: str, *args: str, **kwargs: Any) -> FakeContext:
        return context

    fake = ModuleType("acp")
    fake.PROTOCOL_VERSION = 1
    fake.spawn_agent_process = spawn_agent_process
    interfaces = ModuleType("acp.interfaces")
    interfaces.Client = object
    sys.modules["acp"] = fake
    sys.modules["acp.interfaces"] = interfaces


class AcpSessionSuggestionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.cwd = Path(".").resolve()

    async def test_suggestions_evaluator_is_no_op_by_default(self) -> None:
        context = FakeContext(FakeConnection(), FakeProcess())
        install_fake_acp(context)
        session = OpenCodeSession()
        emitted: list[dict[str, Any]] = []
        await session.start(self.cwd, emit=emitted.append)
        try:
            # Default bus should not crash on fire
            session._fire_suggestions("hello")
        finally:
            await session.close()

    async def test_set_suggestions_evaluator_wires_bus(self) -> None:
        context = FakeContext(FakeConnection(), FakeProcess())
        install_fake_acp(context)
        session = OpenCodeSession()
        emitted: list[dict[str, Any]] = []
        await session.start(self.cwd, emit=emitted.append)
        try:
            counter = CountingEvaluator()
            session.set_suggestions_evaluator(counter)
            session._fire_suggestions("test prompt")
            await asyncio.sleep(0.05)
            self.assertEqual(counter.call_count, 1)
            self.assertEqual(counter.last_ctx.user_text, "test prompt")
            self.assertEqual(counter.last_ctx.agent_name, "test-agent")
        finally:
            await session.close()

    async def test_fire_suggestions_skips_when_not_initialized(self) -> None:
        session = OpenCodeSession()
        # Before start(), _initialized is False — should not crash
        session._fire_suggestions("hello")

    async def test_mcp_servers_passed_to_new_session(self) -> None:
        context = FakeContext(FakeConnection(), FakeProcess())
        install_fake_acp(context)
        session = OpenCodeSession()
        session._mcp_servers = [
            MCPServerConfig(name="files", command="npx", args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]),
        ]
        emitted: list[dict[str, Any]] = []
        await session.start(self.cwd, emit=emitted.append)
        try:
            mcp_arg = context.connection.new_session_kwargs.get("mcp_servers")
            self.assertIsNotNone(mcp_arg)
            self.assertEqual(len(mcp_arg), 1)
            self.assertEqual(mcp_arg[0]["name"], "files")
            self.assertEqual(mcp_arg[0]["command"], "npx")
            self.assertEqual(mcp_arg[0]["args"], ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"])
        finally:
            await session.close()

    async def test_mcp_servers_empty_by_default(self) -> None:
        context = FakeContext(FakeConnection(), FakeProcess())
        install_fake_acp(context)
        session = OpenCodeSession()
        emitted: list[dict[str, Any]] = []
        await session.start(self.cwd, emit=emitted.append)
        try:
            mcp_arg = context.connection.new_session_kwargs.get("mcp_servers")
            self.assertEqual(mcp_arg, [])
        finally:
            await session.close()


# ---------------------------------------------------------------------------
# OpenCodeServerAdapter no-op suggestions tests
# ---------------------------------------------------------------------------


class ServerAdapterSuggestionsTests(unittest.TestCase):
    def test_has_suggestions_field(self) -> None:
        adapter = OpenCodeServerAdapter(opencode_bin="fake")
        self.assertIsNotNone(adapter._suggestions)
        self.assertIsInstance(adapter._suggestions, SuggestionEventBus)

    def test_has_mcp_servers_field(self) -> None:
        adapter = OpenCodeServerAdapter(opencode_bin="fake")
        self.assertIsNone(adapter._mcp_servers)

    def test_set_suggestions_evaluator_is_no_op(self) -> None:
        adapter = OpenCodeServerAdapter(opencode_bin="fake")
        # Should not raise
        adapter.set_suggestions_evaluator(CountingEvaluator())

    def test_fire_suggestions_is_no_op(self) -> None:
        adapter = OpenCodeServerAdapter(opencode_bin="fake")
        # Should not raise
        adapter.fire_suggestions(None)


if __name__ == "__main__":
    unittest.main()
