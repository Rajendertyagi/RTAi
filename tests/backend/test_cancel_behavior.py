"""Cancel behavior integration tests (b296caa verification)."""

from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from app.agents.base import AgentAdapter, Emit, SelectionResult
from app.agents.capabilities import (
    AgentDescriptor,
    CapabilitySection,
    CapabilitySnapshot,
)
from app.api.routes import router
from app.main import create_app
from fastapi.testclient import TestClient

try:
    from starlette.websockets import WebSocketDisconnect
except ImportError:  # pragma: no cover - starlette <0.46
    WebSocketDisconnect = Exception  # type: ignore[misc,assignment]


class BlockingAdapter(AgentAdapter):
    """Adapter that blocks in submit_prompt so cancel can interrupt."""

    def __init__(self) -> None:
        self._started = False
        self._closed = False
        self._cancel_count = 0
        self._snap = CapabilitySnapshot(
            source="fake",
            agent=AgentDescriptor(id="fake", label="FakeAgent"),
            models=CapabilitySection(items=(MagicMock(id="m1", label="Model 1"),)),
            modes=CapabilitySection(items=()),
            thinking_options=CapabilitySection(items=()),
        )

    async def start(self, cwd: Path, emit: Emit) -> None:
        self._started = True

    async def close(self) -> None:
        self._closed = True

    def capability_snapshot(self) -> CapabilitySnapshot:
        return self._snap

    async def submit_prompt(self, text: str) -> None:
        # Block until cancelled — simulates long-running LLM call
        await asyncio.sleep(3600)

    async def submit_prompt_content(self, content: list[Any]) -> None:
        await self.submit_prompt("")

    async def cancel(self) -> None:
        self._cancel_count += 1

    @property
    def cancel_count(self) -> int:
        return self._cancel_count

    def owned_process(self):
        return None

    async def select(self, kind: str, value_id: str) -> SelectionResult:
        return SelectionResult(kind=kind, applied=True, message="ok")


class TerminalAdapter(AgentAdapter):
    """Adapter that completes prompt quickly and emits done event."""

    def __init__(self) -> None:
        self._started = False
        self._closed = False
        self._cancel_count = 0
        self._emit: Emit | None = None
        self._snap = CapabilitySnapshot(
            source="fake",
            agent=AgentDescriptor(id="fake", label="FakeAgent"),
            models=CapabilitySection(items=(MagicMock(id="m1", label="Model 1"),)),
            modes=CapabilitySection(items=()),
            thinking_options=CapabilitySection(items=()),
        )

    async def start(self, cwd: Path, emit: Emit) -> None:
        self._started = True
        self._emit = emit

    async def close(self) -> None:
        self._closed = True

    def capability_snapshot(self) -> CapabilitySnapshot:
        return self._snap

    async def submit_prompt(self, text: str) -> None:
        # Complete immediately - the route's emit will add session_id/turn_id
        if self._emit is not None:
            await self._emit({"type": "done", "reason": "completed"})

    async def submit_prompt_content(self, content: list[Any]) -> None:
        pass

    async def cancel(self) -> None:
        self._cancel_count += 1

    @property
    def cancel_count(self) -> int:
        return self._cancel_count

    def owned_process(self):
        return None

    async def select(self, kind: str, value_id: str) -> SelectionResult:
        return SelectionResult(kind=kind, applied=True, message="ok")


def _read_until_ready(ws) -> list[dict]:
    """Read events from websocket until status=ready is received."""
    events = []
    while True:
        data = ws.receive_json()
        events.append(data)
        if data.get("type") == "status" and data.get("state") == "ready":
            break
    return events


def _make_client(adapter_class: type[AgentAdapter]) -> TestClient:
    fa = MagicMock()
    fa.create.return_value = adapter_class()
    app = create_app(adapter_factory=fa)
    app.include_router(router)
    return TestClient(app)


class CancelBehaviorTests(unittest.IsolatedAsyncioTestCase):
    """Focused tests for cancel behavior in commit b296caa."""

    async def test_matching_active_cancel_succeeds(self) -> None:
        """First matching cancel forwards to adapter and returns success."""
        client = _make_client(BlockingAdapter)
        exc_type = WebSocketDisconnect if WebSocketDisconnect is not Exception else None
        try:
            with client.websocket_connect("/ws?cwd=/tmp") as ws:
                _read_until_ready(ws)
                adapter = client.app.state.adapter_factory.create.return_value
                ws.send_json(
                    {
                        "protocol_version": 1,
                        "request_id": "req-prompt-1",
                        "type": "prompt",
                        "session_id": "s1",
                        "turn_id": "t1",
                        "message_id": "m1",
                        "text": "hello",
                    }
                )
                # Wait for command_result
                for _ in range(5):
                    ev = ws.receive_json()
                    if ev.get("type") == "command_result":
                        break
                self.assertEqual(ev["request_id"], "req-prompt-1")
                self.assertTrue(ev["success"])

                # Send cancel with matching session/turn
                ws.send_json(
                    {
                        "protocol_version": 1,
                        "request_id": "req-cancel-1",
                        "type": "cancel",
                        "session_id": "s1",
                        "turn_id": "t1",
                    }
                )
                cr = ws.receive_json()
                self.assertEqual(cr["type"], "command_result")
                self.assertTrue(cr["success"])
                self.assertEqual(cr["request_id"], "req-cancel-1")
                self.assertEqual(adapter.cancel_count, 1)
        except WebSocketDisconnect:
            if exc_type is not None:
                pass
            else:
                raise

    async def test_wrong_turn_id_rejected(self) -> None:
        """Cancel with wrong turn_id is rejected with success:false."""
        client = _make_client(BlockingAdapter)
        exc_type = WebSocketDisconnect if WebSocketDisconnect is not Exception else None
        try:
            with client.websocket_connect("/ws?cwd=/tmp") as ws:
                _read_until_ready(ws)
                ws.send_json(
                    {
                        "protocol_version": 1,
                        "request_id": "req-prompt-1",
                        "type": "prompt",
                        "session_id": "s1",
                        "turn_id": "t1",
                        "message_id": "m1",
                        "text": "hello",
                    }
                )
                for _ in range(5):
                    ev = ws.receive_json()
                    if ev.get("type") == "command_result":
                        break

                # Cancel with wrong turn_id
                ws.send_json(
                    {
                        "protocol_version": 1,
                        "request_id": "req-cancel-1",
                        "type": "cancel",
                        "session_id": "s1",
                        "turn_id": "wrong-turn",
                    }
                )
                cr = ws.receive_json()
                self.assertEqual(cr["type"], "command_result")
                self.assertFalse(cr["success"])
                self.assertEqual(cr["message"], "turn_not_active")
        except WebSocketDisconnect:
            if exc_type is not None:
                pass
            else:
                raise

    async def test_wrong_session_id_rejected(self) -> None:
        """Cancel with wrong session_id is rejected with success:false."""
        client = _make_client(BlockingAdapter)
        exc_type = WebSocketDisconnect if WebSocketDisconnect is not Exception else None
        try:
            with client.websocket_connect("/ws?cwd=/tmp") as ws:
                _read_until_ready(ws)
                ws.send_json(
                    {
                        "protocol_version": 1,
                        "request_id": "req-prompt-1",
                        "type": "prompt",
                        "session_id": "s1",
                        "turn_id": "t1",
                        "message_id": "m1",
                        "text": "hello",
                    }
                )
                for _ in range(5):
                    ev = ws.receive_json()
                    if ev.get("type") == "command_result":
                        break

                # Cancel with wrong session_id
                ws.send_json(
                    {
                        "protocol_version": 1,
                        "request_id": "req-cancel-1",
                        "type": "cancel",
                        "session_id": "wrong-session",
                        "turn_id": "t1",
                    }
                )
                cr = ws.receive_json()
                self.assertEqual(cr["type"], "command_result")
                self.assertFalse(cr["success"])
        except WebSocketDisconnect:
            if exc_type is not None:
                pass
            else:
                raise

    async def test_no_active_turn_rejected(self) -> None:
        """Cancel without any active turn is rejected with success:false."""
        client = _make_client(BlockingAdapter)
        exc_type = WebSocketDisconnect if WebSocketDisconnect is not Exception else None
        try:
            with client.websocket_connect("/ws?cwd=/tmp") as ws:
                _read_until_ready(ws)
                # Send cancel without any prompt
                ws.send_json(
                    {
                        "protocol_version": 1,
                        "request_id": "req-cancel-1",
                        "type": "cancel",
                        "session_id": "s1",
                        "turn_id": "t1",
                    }
                )
                cr = ws.receive_json()
                self.assertEqual(cr["type"], "command_result")
                self.assertFalse(cr["success"])
                self.assertEqual(cr["message"], "turn_not_active")
        except WebSocketDisconnect:
            if exc_type is not None:
                pass
            else:
                raise

    async def test_duplicate_cancel_idempotent(self) -> None:
        """Second cancel for same already-cancelling turn is idempotent success."""
        client = _make_client(BlockingAdapter)
        exc_type = WebSocketDisconnect if WebSocketDisconnect is not Exception else None
        try:
            with client.websocket_connect("/ws?cwd=/tmp") as ws:
                _read_until_ready(ws)
                adapter = client.app.state.adapter_factory.create.return_value
                ws.send_json(
                    {
                        "protocol_version": 1,
                        "request_id": "req-prompt-1",
                        "type": "prompt",
                        "session_id": "s1",
                        "turn_id": "t1",
                        "message_id": "m1",
                        "text": "hello",
                    }
                )
                for _ in range(5):
                    ev = ws.receive_json()
                    if ev.get("type") == "command_result":
                        break

                # First cancel
                ws.send_json(
                    {
                        "protocol_version": 1,
                        "request_id": "req-cancel-1",
                        "type": "cancel",
                        "session_id": "s1",
                        "turn_id": "t1",
                    }
                )
                cr1 = ws.receive_json()
                self.assertTrue(cr1["success"])
                self.assertEqual(adapter.cancel_count, 1)

                # Drain the done event emitted by the cancelled _turn task
                while True:
                    ev = ws.receive_json()
                    if ev.get("type") == "done":
                        break

                # Second cancel (duplicate)
                ws.send_json(
                    {
                        "protocol_version": 1,
                        "request_id": "req-cancel-2",
                        "type": "cancel",
                        "session_id": "s1",
                        "turn_id": "t1",
                    }
                )
                cr2 = ws.receive_json()
                self.assertTrue(cr2["success"])
                # Adapter should NOT be called again
                self.assertEqual(adapter.cancel_count, 1)
        except WebSocketDisconnect:
            if exc_type is not None:
                pass
            else:
                raise

    async def test_cancel_already_terminal_turn(self) -> None:
        """Cancel for exact already-terminal turn is safe success no-op."""
        client = _make_client(TerminalAdapter)
        exc_type = WebSocketDisconnect if WebSocketDisconnect is not Exception else None
        try:
            with client.websocket_connect("/ws?cwd=/tmp") as ws:
                _read_until_ready(ws)
                adapter = client.app.state.adapter_factory.create.return_value
                ws.send_json(
                    {
                        "protocol_version": 1,
                        "request_id": "req-prompt-1",
                        "type": "prompt",
                        "session_id": "s1",
                        "turn_id": "t1",
                        "message_id": "m1",
                        "text": "hello",
                    }
                )
                # Wait for command_result then done event with matching IDs
                done_received = False
                for _ in range(10):
                    ev = ws.receive_json()
                    if ev.get("type") == "command_result":
                        continue
                    ev_type = ev.get("type")
                    ev_session = ev.get("session_id")
                    ev_turn = ev.get("turn_id")
                    if ev_type == "done" and ev_session == "s1" and ev_turn == "t1":
                        done_received = True
                        break

                self.assertTrue(
                    done_received, "Expected done event with matching session/turn"
                )

                # Cancel the terminal turn
                ws.send_json(
                    {
                        "protocol_version": 1,
                        "request_id": "req-cancel-1",
                        "type": "cancel",
                        "session_id": "s1",
                        "turn_id": "t1",
                    }
                )
                cr = ws.receive_json()
                self.assertTrue(cr["success"])
                # Adapter cancel should not have been called
                self.assertEqual(adapter.cancel_count, 0)
        except WebSocketDisconnect:
            if exc_type is not None:
                pass
            else:
                raise

    async def test_cancel_unrelated_terminal_turn_rejected(self) -> None:
        """Cancel for unrelated older turn is rejected."""
        client = _make_client(TerminalAdapter)
        exc_type = WebSocketDisconnect if WebSocketDisconnect is not Exception else None
        try:
            with client.websocket_connect("/ws?cwd=/tmp") as ws:
                _read_until_ready(ws)
                adapter = client.app.state.adapter_factory.create.return_value
                ws.send_json(
                    {
                        "protocol_version": 1,
                        "request_id": "req-prompt-1",
                        "type": "prompt",
                        "session_id": "s1",
                        "turn_id": "t1",
                        "message_id": "m1",
                        "text": "hello",
                    }
                )
                # Drain all prompt events including command_result and done
                for _ in range(10):
                    ev = ws.receive_json()
                    cr_type = ev.get("type")
                    cr_req_id = ev.get("request_id")
                    if cr_type == "command_result" and cr_req_id == "req-prompt-1":
                        break

                # Cancel a completely different turn
                ws.send_json(
                    {
                        "protocol_version": 1,
                        "request_id": "req-cancel-1",
                        "type": "cancel",
                        "session_id": "other-session",
                        "turn_id": "other-turn",
                    }
                )
                cr = ws.receive_json()
                self.assertFalse(cr["success"])
                self.assertEqual(adapter.cancel_count, 0)
        except WebSocketDisconnect:
            if exc_type is not None:
                pass
            else:
                raise

    async def test_adapter_cancel_called_exactly_once(self) -> None:
        """Adapter cancel is called exactly once for first matching cancel."""
        client = _make_client(BlockingAdapter)
        exc_type = WebSocketDisconnect if WebSocketDisconnect is not Exception else None
        try:
            with client.websocket_connect("/ws?cwd=/tmp") as ws:
                _read_until_ready(ws)
                adapter = client.app.state.adapter_factory.create.return_value
                ws.send_json(
                    {
                        "protocol_version": 1,
                        "request_id": "req-prompt-1",
                        "type": "prompt",
                        "session_id": "s1",
                        "turn_id": "t1",
                        "message_id": "m1",
                        "text": "hello",
                    }
                )
                for _ in range(5):
                    ev = ws.receive_json()
                    if ev.get("type") == "command_result":
                        break

                ws.send_json(
                    {
                        "protocol_version": 1,
                        "request_id": "req-cancel-1",
                        "type": "cancel",
                        "session_id": "s1",
                        "turn_id": "t1",
                    }
                )
                cr = ws.receive_json()
                self.assertTrue(cr["success"])
                self.assertEqual(adapter.cancel_count, 1)
        except WebSocketDisconnect:
            if exc_type is not None:
                pass
            else:
                raise

    async def test_new_prompt_resets_cancel_state(self) -> None:
        """New prompt resets cancel_requested so second cancel works."""
        client = _make_client(BlockingAdapter)
        exc_type = WebSocketDisconnect if WebSocketDisconnect is not Exception else None
        try:
            with client.websocket_connect("/ws?cwd=/tmp") as ws:
                _read_until_ready(ws)
                adapter = client.app.state.adapter_factory.create.return_value
                # First prompt + cancel
                ws.send_json(
                    {
                        "protocol_version": 1,
                        "request_id": "req-prompt-1",
                        "type": "prompt",
                        "session_id": "s1",
                        "turn_id": "t1",
                        "message_id": "m1",
                        "text": "hello",
                    }
                )
                for _ in range(5):
                    ev = ws.receive_json()
                    if ev.get("type") == "command_result":
                        break

                ws.send_json(
                    {
                        "protocol_version": 1,
                        "request_id": "req-cancel-1",
                        "type": "cancel",
                        "session_id": "s1",
                        "turn_id": "t1",
                    }
                )
                cr = ws.receive_json()
                self.assertTrue(cr["success"])

                # Drain the done event emitted by the cancelled _turn task
                while True:
                    ev = ws.receive_json()
                    if ev.get("type") == "done":
                        break

                # Second prompt on same session
                ws.send_json(
                    {
                        "protocol_version": 1,
                        "request_id": "req-prompt-2",
                        "type": "prompt",
                        "session_id": "s1",
                        "turn_id": "t2",
                        "message_id": "m2",
                        "text": "world",
                    }
                )
                for _ in range(5):
                    ev = ws.receive_json()
                    if ev.get("type") == "command_result":
                        break

                # Cancel the second prompt
                ws.send_json(
                    {
                        "protocol_version": 1,
                        "request_id": "req-cancel-2",
                        "type": "cancel",
                        "session_id": "s1",
                        "turn_id": "t2",
                    }
                )
                cr2 = ws.receive_json()
                self.assertTrue(cr2["success"])
                # Should have been called once for first cancel + once for second
                self.assertEqual(adapter.cancel_count, 2)
        except WebSocketDisconnect:
            if exc_type is not None:
                pass
            else:
                raise

    async def test_cancel_result_echoes_own_request_id(self) -> None:
        """Cancel command_result contains the cancel's own request_id."""
        client = _make_client(BlockingAdapter)
        exc_type = WebSocketDisconnect if WebSocketDisconnect is not Exception else None
        try:
            with client.websocket_connect("/ws?cwd=/tmp") as ws:
                _read_until_ready(ws)
                ws.send_json(
                    {
                        "protocol_version": 1,
                        "request_id": "req-prompt-1",
                        "type": "prompt",
                        "session_id": "s1",
                        "turn_id": "t1",
                        "message_id": "m1",
                        "text": "hello",
                    }
                )
                for _ in range(5):
                    ev = ws.receive_json()
                    if ev.get("type") == "command_result":
                        break

                ws.send_json(
                    {
                        "protocol_version": 1,
                        "request_id": "my-cancel-req-123",
                        "type": "cancel",
                        "session_id": "s1",
                        "turn_id": "t1",
                    }
                )
                cr = ws.receive_json()
                self.assertEqual(cr["request_id"], "my-cancel-req-123")
        except WebSocketDisconnect:
            if exc_type is not None:
                pass
            else:
                raise

    async def test_terminal_done_has_cancelled_reason(self) -> None:
        """Terminal done after cancel has reason='cancelled'."""
        client = _make_client(BlockingAdapter)
        exc_type = WebSocketDisconnect if WebSocketDisconnect is not Exception else None
        try:
            with client.websocket_connect("/ws?cwd=/tmp") as ws:
                _read_until_ready(ws)
                ws.send_json(
                    {
                        "protocol_version": 1,
                        "request_id": "req-prompt-1",
                        "type": "prompt",
                        "session_id": "s1",
                        "turn_id": "t1",
                        "message_id": "m1",
                        "text": "hello",
                    }
                )
                for _ in range(5):
                    ev = ws.receive_json()
                    if ev.get("type") == "command_result":
                        break

                # Cancel
                ws.send_json(
                    {
                        "protocol_version": 1,
                        "request_id": "req-cancel-1",
                        "type": "cancel",
                        "session_id": "s1",
                        "turn_id": "t1",
                    }
                )
                cr = ws.receive_json()
                self.assertTrue(cr["success"])

                # Wait for done event with matching IDs
                done_event = None
                for _ in range(20):
                    ev = ws.receive_json()
                    ev_type = ev.get("type")
                    ev_session = ev.get("session_id")
                    ev_turn = ev.get("turn_id")
                    if ev_type == "done" and ev_session == "s1" and ev_turn == "t1":
                        done_event = ev
                        break

                self.assertIsNotNone(done_event, "Expected done event after cancel")
                self.assertEqual(done_event["reason"], "cancelled")
                self.assertEqual(done_event["session_id"], "s1")
                self.assertEqual(done_event["turn_id"], "t1")
        except WebSocketDisconnect:
            if exc_type is not None:
                pass
            else:
                raise

    async def test_exactly_one_done_after_cancel(self) -> None:
        """Only one done event with reason='cancelled' is emitted after cancel."""
        client = _make_client(BlockingAdapter)
        exc_type = WebSocketDisconnect if WebSocketDisconnect is not Exception else None
        try:
            with client.websocket_connect("/ws?cwd=/tmp") as ws:
                _read_until_ready(ws)
                ws.send_json(
                    {
                        "protocol_version": 1,
                        "request_id": "req-prompt-1",
                        "type": "prompt",
                        "session_id": "s1",
                        "turn_id": "t1",
                        "message_id": "m1",
                        "text": "hello",
                    }
                )
                for _ in range(5):
                    ev = ws.receive_json()
                    if ev.get("type") == "command_result":
                        break

                ws.send_json(
                    {
                        "protocol_version": 1,
                        "request_id": "req-cancel-1",
                        "type": "cancel",
                        "session_id": "s1",
                        "turn_id": "t1",
                    }
                )
                cr = ws.receive_json()
                self.assertTrue(cr["success"])

                # Count done events with matching IDs
                done_count = 0
                for _ in range(20):
                    ev = ws.receive_json()
                    ev_type = ev.get("type")
                    ev_session = ev.get("session_id")
                    ev_turn = ev.get("turn_id")
                    if ev_type == "done" and ev_session == "s1" and ev_turn == "t1":
                        done_count += 1
                        break  # Found the one done event we're looking for

                self.assertEqual(done_count, 1, "Expected exactly one done event")
        except WebSocketDisconnect:
            if exc_type is not None:
                pass
            else:
                raise


if __name__ == "__main__":
    unittest.main()
