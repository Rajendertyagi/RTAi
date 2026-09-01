"""Lifecycle logging behavior: chain, correlation, privacy, terminal events.

These tests drive the real WebSocket handler (fake adapter) and the real
adapter/ownership code (fake ACP module) while capturing structured log
records, proving the diagnostic chain exists without ever leaking user or
provider content.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest import mock
from urllib.parse import quote

from app.agents.base import AgentAdapter, Emit, SelectionResult
from app.agents.capabilities import (
    AgentDescriptor,
    CapabilitySection,
    CapabilitySnapshot,
)
from app.agents.opencode_acp import OpenCodeSession
from app.agents.owned_process import OwnedProcess
from app.main import create_app
from fastapi.testclient import TestClient

try:
    from starlette.websockets import WebSocketDisconnect
except ImportError:  # pragma: no cover - starlette <0.46
    WebSocketDisconnect = Exception  # type: ignore[misc,assignment]

SECRET_PROMPT = "SECRET_PROMPT_TEXT"
SECRET_DELTA = "SECRET_DELTA_TEXT"
SECRET_ERROR = "SECRET_ERROR_MESSAGE"
SECRET_AUTH = "SECRET_AUTH_HEADER"

FAKE_BIN = "C:/fake/bin/opencode.exe"


def _snapshot() -> CapabilitySnapshot:
    return CapabilitySnapshot(
        source="fake",
        agent=AgentDescriptor(id="fake", label="FakeAgent"),
        models=CapabilitySection(items=()),
        modes=CapabilitySection(items=()),
        thinking_options=CapabilitySection(items=()),
    )


class StreamingFakeAdapter(AgentAdapter):
    """Emits a delta then a done event for every prompt."""

    def __init__(self) -> None:
        self._emit: Emit | None = None

    async def start(self, cwd: Path, emit: Emit) -> None:
        self._emit = emit
        await emit({"type": "status", "state": "starting", "cwd": str(cwd)})

    async def close(self) -> None:
        pass

    def capability_snapshot(self) -> CapabilitySnapshot:
        return _snapshot()

    async def submit_prompt(self, text: str, turn_id: str = "", message_id: str = "") -> None:
        assert self._emit is not None
        await self._emit({"type": "delta", "text": SECRET_DELTA})
        await self._emit({"type": "done"})

    async def submit_prompt_content(self, content: list[Any], turn_id: str = "", message_id: str = "") -> None:
        pass

    async def cancel(self) -> None:
        pass

    def owned_process(self) -> None:
        return None

    async def select(self, kind: str, value_id: str) -> SelectionResult:
        return SelectionResult(kind=kind, applied=True, message="ok")


class QuietFakeAdapter(StreamingFakeAdapter):
    """Emits nothing for a prompt; used for cancel/disconnect flows."""

    async def submit_prompt(self, text: str, turn_id: str = "", message_id: str = "") -> None:
        # Hold long enough for a cancel command to arrive and interrupt us.
        await asyncio.sleep(10)


class ErrorFakeAdapter(StreamingFakeAdapter):
    """Raises an exception whose message must never reach the logs."""

    async def submit_prompt(self, text: str, turn_id: str = "", message_id: str = "") -> None:
        raise RuntimeError(SECRET_ERROR)


def _read_until_ready(ws) -> list[dict]:
    events = []
    while True:
        data = ws.receive_json()
        events.append(data)
        if data.get("type") == "status" and data.get("state") == "ready":
            break
    return events


def _make_client(adapter: AgentAdapter) -> TestClient:
    fa = mock.MagicMock()
    fa.create.return_value = adapter
    app = create_app(adapter_factory=fa)
    return TestClient(app)


def _ws_url(self: unittest.TestCase) -> str:
    """Return a /ws URL pointing at a real temp directory (exists on all OSes).

    ``/tmp`` is not portable: on Windows it resolves to ``<drive>:\\tmp``,
    which does not exist on CI runners.  A freshly created temp directory
    guarantees the connection is accepted so the lifecycle chain runs.
    """
    project = Path(tempfile.mkdtemp(prefix="rtai-lifecycle-"))
    self.addCleanup(shutil.rmtree, project, ignore_errors=True)
    return f"/ws?cwd={quote(str(project))}"


def _events_of(records: list[logging.LogRecord]) -> list[str]:
    return [getattr(r, "event", "") for r in records]


class LifecycleChainTests(unittest.IsolatedAsyncioTestCase):
    def test_prompt_lifecycle_chain_logged(self) -> None:
        client = _make_client(StreamingFakeAdapter())
        with self.assertLogs("app", level="DEBUG") as captured:
            try:
                with client.websocket_connect(_ws_url(self)) as ws:
                    _read_until_ready(ws)
                    ws.send_json({
                        "protocol_version": 1,
                        "request_id": "r1",
                        "type": "prompt",
                        "session_id": "session-1234567890",
                        "turn_id": "turn-1234567890",
                        "message_id": "message-1234567890",
                        "text": SECRET_PROMPT,
                    })
                    while True:
                        ev = ws.receive_json()
                        if ev.get("type") == "done":
                            self.assertEqual(ev.get("protocol_version"), 1)
                            break
            except WebSocketDisconnect:
                pass
        events = _events_of(captured.records)
        for expected in (
            "prompt_received",
            "command_validated",
            "adapter_prompt_started",
            "adapter_event_received",
            "event_normalized",
            "websocket_event_sent",
            "terminal_event_received",
            "turn_finalized",
        ):
            self.assertIn(expected, events)

    def test_correlation_aliases_consistent_across_chain(self) -> None:
        client = _make_client(StreamingFakeAdapter())
        with self.assertLogs("app", level="DEBUG") as captured:
            try:
                with client.websocket_connect(_ws_url(self)) as ws:
                    _read_until_ready(ws)
                    ws.send_json({
                        "protocol_version": 1,
                        "request_id": "request-1234567890",
                        "type": "prompt",
                        "session_id": "session-1234567890",
                        "turn_id": "turn-1234567890",
                        "message_id": "message-1234567890",
                        "text": "hello",
                    })
                    while True:
                        ev = ws.receive_json()
                        if ev.get("type") == "done":
                            break
            except WebSocketDisconnect:
                pass
        for record in captured.records:
            meta = getattr(record, "meta", None)
            if not isinstance(meta, dict):
                continue
            if "session" in meta:
                self.assertEqual(meta["session"], "session-")
            if "turn" in meta:
                self.assertEqual(meta["turn"], "turn-123")

    def test_info_level_has_no_per_delta_noise(self) -> None:
        client = _make_client(StreamingFakeAdapter())
        with self.assertLogs("app", level="INFO") as captured:
            try:
                with client.websocket_connect(_ws_url(self)) as ws:
                    _read_until_ready(ws)
                    ws.send_json({
                        "protocol_version": 1,
                        "request_id": "r1",
                        "type": "prompt",
                        "session_id": "s1",
                        "turn_id": "t1",
                        "message_id": "m1",
                        "text": "hello",
                    })
                    while True:
                        ev = ws.receive_json()
                        if ev.get("type") == "done":
                            break
            except WebSocketDisconnect:
                pass
        events = _events_of(captured.records)
        for noisy in ("adapter_event_received", "event_normalized", "websocket_event_sent"):
            self.assertNotIn(noisy, events)
        self.assertIn("turn_finalized", events)


class PrivacyTests(unittest.IsolatedAsyncioTestCase):
    def test_no_prompt_delta_or_error_content_in_logs(self) -> None:
        client = _make_client(ErrorFakeAdapter())
        with self.assertLogs("app", level="DEBUG") as captured:
            try:
                with client.websocket_connect(_ws_url(self)) as ws:
                    _read_until_ready(ws)
                    ws.send_json({
                        "protocol_version": 1,
                        "request_id": "r1",
                        "type": "prompt",
                        "session_id": "s1",
                        "turn_id": "t1",
                        "message_id": "m1",
                        "text": SECRET_PROMPT,
                    })
                    while True:
                        ev = ws.receive_json()
                        if ev.get("type") == "error":
                            break
            except WebSocketDisconnect:
                pass
        rendered = "\n".join(captured.output)
        for secret in (SECRET_PROMPT, SECRET_DELTA, SECRET_ERROR, SECRET_AUTH):
            self.assertNotIn(secret, rendered)
        # The failure category is logged, never the raw message.
        events = _events_of(captured.records)
        self.assertIn("turn_failed", events)
        failed_meta = [
            getattr(r, "meta", None)
            for r in captured.records
            if getattr(r, "event", "") == "turn_failed"
        ]
        self.assertTrue(failed_meta)
        self.assertEqual(failed_meta[0].get("error"), "RuntimeError")


class TerminalEventTests(unittest.IsolatedAsyncioTestCase):
    def test_cancel_produces_terminal_log(self) -> None:
        client = _make_client(QuietFakeAdapter())
        with self.assertLogs("app", level="INFO") as captured:
            try:
                with client.websocket_connect(_ws_url(self)) as ws:
                    _read_until_ready(ws)
                    ws.send_json({
                        "protocol_version": 1,
                        "request_id": "r1",
                        "type": "prompt",
                        "session_id": "s1",
                        "turn_id": "t1",
                        "message_id": "m1",
                        "text": "hello",
                    })
                    while True:
                        ev = ws.receive_json()
                        if ev.get("type") == "command_result":
                            break
                    ws.send_json({
                        "protocol_version": 1,
                        "request_id": "r2",
                        "type": "cancel",
                        "session_id": "s1",
                        "turn_id": "t1",
                    })
                    while True:
                        ev = ws.receive_json()
                        if ev.get("type") == "done":
                            self.assertEqual(ev.get("reason"), "cancelled")
                            break
            except WebSocketDisconnect:
                pass
        events = _events_of(captured.records)
        self.assertIn("cancellation_requested", events)
        self.assertIn("turn_cancelled", events)

    def test_disconnect_logged(self) -> None:
        client = _make_client(QuietFakeAdapter())
        with self.assertLogs("app", level="INFO") as captured:
            try:
                with client.websocket_connect(_ws_url(self)) as ws:
                    _read_until_ready(ws)
            except WebSocketDisconnect:
                pass
        events = _events_of(captured.records)
        self.assertIn("disconnect", events)
        self.assertIn("connection_closing", events)
        self.assertIn("adapter_cleanup", events)


class OwnedProcessLoggingTests(unittest.IsolatedAsyncioTestCase):
    async def test_owned_process_cleanup_logged(self) -> None:
        handle = mock.MagicMock()

        async def cooperative() -> None:
            return None

        owned = OwnedProcess(
            handle=handle,
            pid=4242,
            argv=("opencode", "acp"),
            cooperative_close=cooperative,
        )
        with self.assertLogs("app", level="INFO") as captured:
            await owned.close()
        events = _events_of(captured.records)
        self.assertIn("owned_process_closed", events)


class AcpFallbackLoggingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.cwd = Path(os.getcwd()).resolve()
        env_patcher = mock.patch.dict(os.environ, {"OPENCODE_BIN": ""})
        env_patcher.start()
        self.addCleanup(env_patcher.stop)
        which_patcher = mock.patch("shutil.which", return_value=FAKE_BIN)
        which_patcher.start()
        self.addCleanup(which_patcher.stop)

    async def test_agent_info_none_fallback_logged(self) -> None:
        context = FakeContext(FakeConnection(agent_info=None), FakeProcess())
        install_fake_acp(context)
        session = OpenCodeSession()
        with self.assertLogs("app", level="INFO") as captured:
            await session.start(self.cwd, emit=lambda event: None)
            await session.close()
        events = _events_of(captured.records)
        self.assertIn("acp_agent_info_fallback", events)
        self.assertNotIn("acp_agent_info_available", events)
        self.assertIn("acp_session_created", events)
        self.assertIn("owned_process_closed", events)


class FakeProcess:
    def __init__(self) -> None:
        self.pid = 4321
        self.kill_calls = 0

    def kill(self) -> None:
        self.kill_calls += 1


class FakeContext:
    def __init__(self, connection: FakeConnection, process: FakeProcess) -> None:
        self.connection = connection
        self.process = process
        self.exit_calls = 0

    async def __aenter__(self) -> tuple[FakeConnection, FakeProcess]:
        return self.connection, self.process

    async def __aexit__(self, *exc: object) -> None:
        self.exit_calls += 1


class FakeConnection:
    def __init__(self, agent_info: Any | None = None) -> None:
        self._agent_info = agent_info

    async def initialize(self, **kwargs: Any) -> Any:
        class Response:
            agentInfo = self._agent_info
            protocolVersion = 1

        return Response()

    async def new_session(self, **kwargs: Any) -> Any:
        class Session:
            session_id = "session-owned-1"

        return Session()


def install_fake_acp(context: FakeContext) -> None:
    """Replace sys.modules['acp'] with a fake that always yields ``context``."""

    def spawn_agent_process(
        to_client: object, command: str, *args: str, **kwargs: Any
    ) -> FakeContext:
        return context

    fake = ModuleType("acp")
    fake.PROTOCOL_VERSION = 1  # type: ignore[attr-defined]
    fake.spawn_agent_process = spawn_agent_process  # type: ignore[attr-defined]
    interfaces = ModuleType("acp.interfaces")
    interfaces.Client = object  # type: ignore[attr-defined]
    sys.modules["acp"] = fake
    sys.modules["acp.interfaces"] = interfaces


if __name__ == "__main__":
    unittest.main()
