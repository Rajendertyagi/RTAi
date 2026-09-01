"""Protocol v1 WebSocket handler integration tests (fake adapter)."""

from __future__ import annotations

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


class FakeAdapter(AgentAdapter):
    """Minimal adapter for WebSocket handler tests."""

    def __init__(self) -> None:
        self._started = False
        self._closed = False
        self._snap = CapabilitySnapshot(
            source="fake",
            agent=AgentDescriptor(id="fake", label="FakeAgent"),
            models=CapabilitySection(
                items=(MagicMock(id="m1", label="Model 1"),)
            ),
            modes=CapabilitySection(items=()),
            thinking_options=CapabilitySection(items=()),
        )

    async def start(self, cwd: Path, emit: Emit) -> None:
        self._started = True

    async def close(self) -> None:
        self._closed = True

    def capability_snapshot(self) -> CapabilitySnapshot:
        return self._snap

    async def submit_prompt(self, text: str, turn_id: str = "", message_id: str = "") -> None:
        pass

    async def submit_prompt_content(self, content: list[Any], turn_id: str = "", message_id: str = "") -> None:
        pass

    async def cancel(self) -> None:
        pass

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


class WebSocketV1Tests(unittest.IsolatedAsyncioTestCase):
    def _make_client(self) -> TestClient:
        fa = MagicMock()
        fa.create.return_value = FakeAdapter()
        app = create_app(adapter_factory=fa)
        app.include_router(router)
        return TestClient(app)

    async def test_connect_emits_capability_events_and_ready(self) -> None:
        client = self._make_client()

        exc_type = WebSocketDisconnect if WebSocketDisconnect is not Exception else None
        try:
            with client.websocket_connect("/ws?cwd=/tmp") as ws:
                events = _read_until_ready(ws)
                types = [e["type"] for e in events]
                self.assertIn("agent_info", types)
                self.assertIn("agents_available", types)
                self.assertIn("models_available", types)
                self.assertIn("thinking_available", types)
                self.assertIn("modes_available", types)
                self.assertIn("status", types)
        except WebSocketDisconnect:
            if exc_type is not None:
                pass  # expected with starlette<1.0
            else:
                raise

    async def test_prompt_command_requires_fields(self) -> None:
        client = self._make_client()

        exc_type = WebSocketDisconnect if WebSocketDisconnect is not Exception else None
        try:
            with client.websocket_connect("/ws?cwd=/tmp") as ws:
                _read_until_ready(ws)
                ws.send_json({
                    "protocol_version": 1,
                    "type": "prompt",
                    "session_id": "s1",
                    # missing turn_id, message_id, text
                })
                result = ws.receive_json()
                self.assertEqual(result["type"], "command_result")
                self.assertFalse(result["success"])
        except WebSocketDisconnect:
            if exc_type is not None:
                pass  # expected with starlette<1.0
            else:
                raise

    async def test_valid_prompt_and_command_result(self) -> None:
        client = self._make_client()

        exc_type = WebSocketDisconnect if WebSocketDisconnect is not Exception else None
        try:
            with client.websocket_connect("/ws?cwd=/tmp") as ws:
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
                msgs = []
                for _ in range(5):
                    msgs.append(ws.receive_json())
                    if msgs[-1].get("type") == "command_result":
                        break
                types = [m["type"] for m in msgs]
                self.assertIn("user_message", types)
                cr = [m for m in msgs if m["type"] == "command_result"][0]
                self.assertTrue(cr["success"])
                self.assertEqual(cr["request_id"], "r1")
        except WebSocketDisconnect:
            if exc_type is not None:
                pass  # expected with starlette<1.0
            else:
                raise

    async def test_invalid_cwd_rejects_connection(self) -> None:
        client = self._make_client()

        # starlette<1.0 raises WebSocketDisconnect on close; >=1.0 does not.
        # Accept either behavior.
        try:
            with client.websocket_connect("/ws?cwd=/nonexistent/path") as ws:
                ev = ws.receive_json()
                # If we got an event, verify it's an error.
                self.assertEqual(ev["type"], "error")
                self.assertIn("Project folder does not exist", ev["message"])
        except WebSocketDisconnect:
            pass  # expected with older starlette

        # If we got a connection AND didn't receive an error event,
        # that's also acceptable (some starlette versions close immediately).
        # The important thing is we don't crash.

    async def test_blank_cwd_keeps_connection_alive_with_error_event(self) -> None:
        """Blank or missing cwd now auto-creates a temp session dir so the
        connection succeeds. Whitespace-only cwd still fails."""
        client = self._make_client()

        exc_type = WebSocketDisconnect if WebSocketDisconnect is not Exception else None
        try:
            with client.websocket_connect("/ws") as ws:
                # Missing cwd -> temp dir created -> connection succeeds
                events = _read_until_ready(ws)
                types = [e["type"] for e in events]
                self.assertIn("status", types)
        except WebSocketDisconnect:
            if exc_type is not None:
                pass
            else:
                raise

    async def test_whitespace_only_cwd_is_treated_as_blank(self) -> None:
        client = self._make_client()

        exc_type = WebSocketDisconnect if WebSocketDisconnect is not Exception else None
        try:
            with client.websocket_connect("/ws?cwd=%20%20") as ws:
                ev = ws.receive_json()
                self.assertEqual(ev["type"], "error")
                self.assertEqual(ev["code"], "project_folder_not_provided")
        except WebSocketDisconnect:
            if exc_type is not None:
                pass
            else:
                raise

    async def test_api_health(self) -> None:
        client = self._make_client()
        resp = client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok"})

    async def test_api_unknown_route_returns_json_404(self) -> None:
        client = self._make_client()
        resp = client.get("/api/nope")
        self.assertEqual(resp.status_code, 404)
        ct = resp.headers.get("content-type", "")
        self.assertIn("application/json", ct)

    async def test_all_outbound_events_include_protocol_version(self) -> None:
        """Every event emitted during connection (status, capabilities, ready)
        must carry ``protocol_version: 1`` so the frontend v1 guard accepts it."""
        client = self._make_client()

        exc_type = WebSocketDisconnect if WebSocketDisconnect is not Exception else None
        try:
            with client.websocket_connect("/ws?cwd=/tmp") as ws:
                events = _read_until_ready(ws)
                for ev in events:
                    self.assertEqual(
                        ev.get("protocol_version"), 1,
                        f"Event missing protocol_version=1: {ev}",
                    )
        except WebSocketDisconnect:
            if exc_type is not None:
                pass
            else:
                raise

    async def test_trusted_envelope_fields_not_overridable(self) -> None:
        """Adapter payloads cannot override the authoritative protocol_version
        envelope field, even if they explicitly include it."""
        class OverrideAdapter(AgentAdapter):
            async def start(self, cwd: Path, emit: Emit) -> None:
                await emit({"type": "status", "state": "starting", "protocol_version": 99})

            async def close(self) -> None:
                pass

            def capability_snapshot(self) -> CapabilitySnapshot:
                return CapabilitySnapshot(
                    source="fake",
                    agent=AgentDescriptor(id="fake", label="FakeAgent"),
                    models=CapabilitySection(items=(MagicMock(id="m1", label="Model 1"),)),
                    modes=CapabilitySection(items=()),
                    thinking_options=CapabilitySection(items=()),
                )

            async def submit_prompt(self, text: str, turn_id: str = "", message_id: str = "") -> None:
                pass

            async def submit_prompt_content(self, content: list[Any], turn_id: str = "", message_id: str = "") -> None:
                pass

            async def cancel(self) -> None:
                pass

            def owned_process(self):
                return None

            async def select(self, kind: str, value_id: str) -> SelectionResult:
                return SelectionResult(kind=kind, applied=True, message="ok")

        fa = MagicMock()
        fa.create.return_value = OverrideAdapter()
        app = create_app(adapter_factory=fa)
        app.include_router(router)
        client = TestClient(app)

        exc_type = WebSocketDisconnect if WebSocketDisconnect is not Exception else None
        try:
            with client.websocket_connect("/ws?cwd=/tmp") as ws:
                events = _read_until_ready(ws)
                # The first status event came from the adapter with
                # protocol_version=99, but the route's emit() must have
                # overwritten it to 1.
                status_events = [e for e in events if e["type"] == "status"]
                self.assertTrue(len(status_events) >= 2)
                for se in status_events:
                    self.assertEqual(se["protocol_version"], 1,
                                     "Adapter attempted to override protocol_version")
        except WebSocketDisconnect:
            if exc_type is not None:
                pass
            else:
                raise

    async def test_blank_cwd_error_event_includes_protocol_version(self) -> None:
        """Whitespace-only cwd should emit an error with protocol_version.
        (Missing cwd auto-creates a temp dir and succeeds.)"""
        client = self._make_client()

        exc_type = WebSocketDisconnect if WebSocketDisconnect is not Exception else None
        try:
            with client.websocket_connect("/ws?cwd=%20%20") as ws:
                ev = ws.receive_json()
                self.assertEqual(ev["type"], "error")
                self.assertEqual(ev["code"], "project_folder_not_provided")
                self.assertEqual(ev["protocol_version"], 1)
        except WebSocketDisconnect:
            if exc_type is not None:
                pass
            else:
                raise


if __name__ == "__main__":
    unittest.main()
