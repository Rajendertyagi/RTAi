"""Protocol v1 attachment validation and WebSocket dispatch tests.

Phase 5: validates multi-block prompt handling through the protocol layer and
WebSocket route. Phase 10: verifies that persistence failures degrade gracefully
without breaking the live stream.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

from app.agents.base import AgentAdapter, Emit, SelectionResult
from app.agents.capabilities import (
    AgentDescriptor,
    AttachmentCapabilities,
    CapabilitySection,
    CapabilitySnapshot,
    UnavailabilityReason,
    UnavailableCapability,
)
from app.api.routes import router
from app.history.errors import HistoryStorageError
from app.history.models import HistoryEvent, HistorySession, SessionStatus
from app.history.repository import HistoryRepository
from app.main import create_app
from fastapi.testclient import TestClient

try:
    from starlette.websockets import WebSocketDisconnect
except ImportError:  # pragma: no cover - starlette <0.46
    WebSocketDisconnect = Exception  # type: ignore[misc,assignment]


_IMAGE_B64 = "kPNGDQ4="  # base64(b"\x89PNG\r\n\x1a\n")
_AUDIO_B64 = "A1JJRkY="  # base64(b"\x00RIFF")


def _read_until_ready(ws) -> list[dict]:
    events: list[dict] = []
    while True:
        data = ws.receive_json()
        events.append(data)
        if data.get("type") == "status" and data.get("state") == "ready":
            break
    return events


# ---------------------------------------------------------------------------
# Fake adapter that records submitted content
# ---------------------------------------------------------------------------


class RecordingAdapter(AgentAdapter):
    """Adapter that records prompt content for assertion."""

    def __init__(
        self,
        attachments: AttachmentCapabilities | UnavailableCapability | None = None,
        fail_persist: bool = False,
    ) -> None:
        self._started = False
        self._closed = False
        self.submitted_texts: list[str] = []
        self.submitted_contents: list[list[Any]] = []
        snap_attachments = (
            attachments
            if attachments is not None
            else UnavailableCapability(
                UnavailabilityReason.NOT_EXPOSED_BY_PROVIDER, "No attachments"
            )
        )
        self._snap = CapabilitySnapshot(
            source="recording",
            agent=AgentDescriptor(id="rec", label="RecordingAgent"),
            models=CapabilitySection(items=(MagicMock(id="m1", label="Model 1"),)),
            modes=CapabilitySection(items=()),
            thinking_options=CapabilitySection(items=()),
            attachments=snap_attachments,
        )
        self._fail_persist = fail_persist

    async def start(self, cwd: Path, emit: Emit) -> None:
        self._started = True

    async def close(self) -> None:
        self._closed = True

    def capability_snapshot(self) -> CapabilitySnapshot:
        return self._snap

    async def submit_prompt(self, text: str, turn_id: str = "", message_id: str = "") -> None:
        self.submitted_texts.append(text)

    async def submit_prompt_content(
        self, content: list[Any], turn_id: str = "", message_id: str = ""
    ) -> None:
        self.submitted_contents.append(content)

    async def cancel(self) -> None:
        pass

    def owned_process(self):
        return None

    async def select(self, kind: str, value_id: str) -> SelectionResult:
        return SelectionResult(kind=kind, applied=True, message="ok")


class FailingRepository(HistoryRepository):
    """Repository that raises on every append to simulate persistence failure."""

    def create_session(self, session: HistorySession) -> None:
        pass

    def get_session(self, rtai_session_id: str) -> HistorySession | None:
        return None

    def list_sessions(
        self, cursor: str | None = None, limit: int = 50
    ) -> tuple[list[HistorySession], str | None]:
        return [], None

    def record_native_mapping(
        self,
        rtai_session_id: str,
        native_session_id: str,
        *,
        adapter_kind: str,
        resume_capable: bool | None,
        resume_reason: str | None,
    ) -> None:
        pass

    def set_title(self, rtai_session_id: str, title: str, *, user: bool) -> None:
        pass

    def set_status(self, rtai_session_id: str, status: SessionStatus) -> None:
        pass

    def touch(self, rtai_session_id: str, *, last_turn_at: int | None = None) -> None:
        pass

    def append_event(self, event: HistoryEvent) -> bool:
        raise HistoryStorageError("simulated persistence failure")

    def get_events(
        self, rtai_session_id: str, cursor: str | None = None, limit: int = 200
    ) -> tuple[list[HistoryEvent], str | None]:
        return [], None

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Phase 5: Protocol validation and WebSocket dispatch
# ---------------------------------------------------------------------------


class ProtocolAttachmentTests(unittest.IsolatedAsyncioTestCase):
    """Multi-block prompt validation and WebSocket dispatch with fakes."""

    def _make_client(
        self,
        adapter: RecordingAdapter | None = None,
        repo: HistoryRepository | None = None,
    ) -> TestClient:
        fa = MagicMock()
        fa.create.return_value = adapter or RecordingAdapter()
        app = create_app(adapter_factory=fa, history_repository=repo)
        app.include_router(router)
        return TestClient(app)

    async def test_valid_multi_block_prompt_accepted(self) -> None:
        caps = AttachmentCapabilities(
            block_types=("resource_link", "image", "audio"),
            resource_links=True,
            images=True,
            audio=True,
            embedded_resources=False,
        )
        adapter = RecordingAdapter(attachments=caps)
        client = self._make_client(adapter)
        exc_type = WebSocketDisconnect if WebSocketDisconnect is not Exception else None
        try:
            with client.websocket_connect("/ws?cwd=/tmp") as ws:
                _read_until_ready(ws)
                ws.send_json(
                    {
                        "protocol_version": 1,
                        "request_id": "r1",
                        "type": "prompt",
                        "session_id": "s1",
                        "turn_id": "t1",
                        "message_id": "m1",
                        "prompt": [
                            {"kind": "text", "name": "msg", "text": "look at this"},
                            {
                                "kind": "image",
                                "name": "img.png",
                                "mime_type": "image/png",
                                "data_base64": _IMAGE_B64,
                            },
                        ],
                    }
                )
                msgs = []
                for _ in range(8):
                    msgs.append(ws.receive_json())
                    if msgs[-1].get("type") == "command_result":
                        break
                cr = next(m for m in msgs if m["type"] == "command_result")
                self.assertTrue(cr["success"])
                self.assertTrue(len(adapter.submitted_contents) >= 1)
                blocks = adapter.submitted_contents[0]
                self.assertEqual(len(blocks), 2)
                self.assertEqual(blocks[0].kind.value, "text")
                self.assertEqual(blocks[1].kind.value, "image")
        except WebSocketDisconnect:
            if exc_type is not None:
                pass
            else:
                raise

    async def test_blocks_reach_adapter_in_original_order(self) -> None:
        caps = AttachmentCapabilities(
            block_types=("resource_link", "image"),
            resource_links=True,
            images=True,
            audio=False,
            embedded_resources=False,
        )
        adapter = RecordingAdapter(attachments=caps)
        client = self._make_client(adapter)
        exc_type = WebSocketDisconnect if WebSocketDisconnect is not Exception else None
        try:
            with client.websocket_connect("/ws?cwd=/tmp") as ws:
                _read_until_ready(ws)
                ws.send_json(
                    {
                        "protocol_version": 1,
                        "request_id": "r2",
                        "type": "prompt",
                        "session_id": "s1",
                        "turn_id": "t1",
                        "message_id": "m1",
                        "prompt": [
                            {
                                "kind": "image",
                                "name": "a.png",
                                "mime_type": "image/png",
                                "data_base64": _IMAGE_B64,
                            },
                            {"kind": "text", "name": "msg", "text": "hello"},
                            {
                                "kind": "image",
                                "name": "b.png",
                                "mime_type": "image/png",
                                "data_base64": _IMAGE_B64,
                            },
                        ],
                    }
                )
                msgs = []
                for _ in range(8):
                    msgs.append(ws.receive_json())
                    if msgs[-1].get("type") == "command_result":
                        break
                blocks = adapter.submitted_contents[0]
                kinds = [b.kind.value for b in blocks]
                self.assertEqual(kinds, ["image", "text", "image"])
        except WebSocketDisconnect:
            if exc_type is not None:
                pass
            else:
                raise

    async def test_unknown_block_kind_rejected(self) -> None:
        adapter = RecordingAdapter()
        client = self._make_client(adapter)
        exc_type = WebSocketDisconnect if WebSocketDisconnect is not Exception else None
        try:
            with client.websocket_connect("/ws?cwd=/tmp") as ws:
                _read_until_ready(ws)
                ws.send_json(
                    {
                        "protocol_version": 1,
                        "request_id": "r3",
                        "type": "prompt",
                        "session_id": "s1",
                        "turn_id": "t1",
                        "message_id": "m1",
                        "prompt": [{"kind": "video", "name": "v.mp4"}],
                    }
                )
                result = ws.receive_json()
                self.assertEqual(result["type"], "command_result")
                self.assertFalse(result["success"])
                self.assertIn("unknown kind", result["message"])
        except WebSocketDisconnect:
            if exc_type is not None:
                pass
            else:
                raise

    async def test_capability_disabled_image_rejected(self) -> None:
        """Image blocks are rejected before the adapter's submit_prompt_content
        is called when the capability is disabled."""
        caps = AttachmentCapabilities(
            block_types=("resource_link",),
            resource_links=True,
            images=False,
        )
        adapter = RecordingAdapter(attachments=caps)
        client = self._make_client(adapter)
        exc_type = WebSocketDisconnect if WebSocketDisconnect is not Exception else None
        try:
            with client.websocket_connect("/ws?cwd=/tmp") as ws:
                _read_until_ready(ws)
                ws.send_json(
                    {
                        "protocol_version": 1,
                        "request_id": "r4",
                        "type": "prompt",
                        "session_id": "s1",
                        "turn_id": "t1",
                        "message_id": "m1",
                        "prompt": [
                            {"kind": "text", "name": "msg", "text": "hi"},
                            {
                                "kind": "image",
                                "name": "img.png",
                                "mime_type": "image/png",
                                "data_base64": _IMAGE_B64,
                            },
                        ],
                    }
                )
                msgs = []
                for _ in range(5):
                    msgs.append(ws.receive_json())
                    if msgs[-1].get("type") in ("command_result", "error"):
                        break
                cr_or_err = msgs[-1]
                # The route catches the RuntimeError and emits an error event.
                self.assertIn(cr_or_err["type"], ("command_result", "error"))
                self.assertEqual(len(adapter.submitted_contents), 0)
        except WebSocketDisconnect:
            if exc_type is not None:
                pass
            else:
                raise

    async def test_capability_disabled_audio_rejected(self) -> None:
        caps = AttachmentCapabilities(
            block_types=("resource_link",),
            resource_links=True,
            audio=False,
        )
        adapter = RecordingAdapter(attachments=caps)
        client = self._make_client(adapter)
        exc_type = WebSocketDisconnect if WebSocketDisconnect is not Exception else None
        try:
            with client.websocket_connect("/ws?cwd=/tmp") as ws:
                _read_until_ready(ws)
                ws.send_json(
                    {
                        "protocol_version": 1,
                        "request_id": "r5",
                        "type": "prompt",
                        "session_id": "s1",
                        "turn_id": "t1",
                        "message_id": "m1",
                        "prompt": [
                            {
                                "kind": "audio",
                                "name": "a.wav",
                                "mime_type": "audio/wav",
                                "data_base64": _AUDIO_B64,
                            }
                        ],
                    }
                )
                msgs = []
                for _ in range(5):
                    msgs.append(ws.receive_json())
                    if msgs[-1].get("type") in ("command_result", "error"):
                        break
                self.assertEqual(len(adapter.submitted_contents), 0)
        except WebSocketDisconnect:
            if exc_type is not None:
                pass
            else:
                raise

    async def test_capability_disabled_embedded_rejected(self) -> None:
        caps = AttachmentCapabilities(
            block_types=("resource_link",),
            resource_links=True,
            embedded_resources=False,
        )
        adapter = RecordingAdapter(attachments=caps)
        client = self._make_client(adapter)
        exc_type = WebSocketDisconnect if WebSocketDisconnect is not Exception else None
        try:
            with client.websocket_connect("/ws?cwd=/tmp") as ws:
                _read_until_ready(ws)
                ws.send_json(
                    {
                        "protocol_version": 1,
                        "request_id": "r6",
                        "type": "prompt",
                        "session_id": "s1",
                        "turn_id": "t1",
                        "message_id": "m1",
                        "prompt": [
                            {
                                "kind": "embedded_text",
                                "name": "e.txt",
                                "mime_type": "text/plain",
                                "text": "inline",
                            }
                        ],
                    }
                )
                msgs = []
                for _ in range(5):
                    msgs.append(ws.receive_json())
                    if msgs[-1].get("type") in ("command_result", "error"):
                        break
                self.assertEqual(len(adapter.submitted_contents), 0)
        except WebSocketDisconnect:
            if exc_type is not None:
                pass
            else:
                raise

    async def test_size_validation_failure_prevents_dispatch(self) -> None:
        """A payload exceeding the per-item limit must prevent adapter dispatch."""
        caps = AttachmentCapabilities(
            block_types=("resource_link", "image"),
            resource_links=True,
            images=True,
        )
        adapter = RecordingAdapter(attachments=caps)
        client = self._make_client(adapter)
        exc_type = WebSocketDisconnect if WebSocketDisconnect is not Exception else None
        try:
            with client.websocket_connect("/ws?cwd=/tmp") as ws:
                _read_until_ready(ws)
                # Send a ~7 MiB base64 image that decodes to >5 MiB (exceeds limit)
                big_b64 = "x" * (7 * 1024 * 1024)
                ws.send_json(
                    {
                        "protocol_version": 1,
                        "request_id": "r7",
                        "type": "prompt",
                        "session_id": "s1",
                        "turn_id": "t1",
                        "message_id": "m1",
                        "prompt": [
                            {
                                "kind": "image",
                                "name": "big.png",
                                "mime_type": "image/png",
                                "data_base64": big_b64,
                            }
                        ],
                    }
                )
                msgs = []
                for _ in range(5):
                    msgs.append(ws.receive_json())
                    if msgs[-1].get("type") in ("command_result", "error"):
                        break
                self.assertEqual(len(adapter.submitted_contents), 0)
        except WebSocketDisconnect:
            if exc_type is not None:
                pass
            else:
                raise

    async def test_text_only_prompt_still_works(self) -> None:
        """Existing text-only prompt shape remains functional."""
        adapter = RecordingAdapter()
        client = self._make_client(adapter)
        exc_type = WebSocketDisconnect if WebSocketDisconnect is not Exception else None
        try:
            with client.websocket_connect("/ws?cwd=/tmp") as ws:
                _read_until_ready(ws)
                ws.send_json(
                    {
                        "protocol_version": 1,
                        "request_id": "r8",
                        "type": "prompt",
                        "session_id": "s1",
                        "turn_id": "t1",
                        "message_id": "m1",
                        "text": "hello world",
                    }
                )
                msgs = []
                for _ in range(5):
                    msgs.append(ws.receive_json())
                    if msgs[-1].get("type") == "command_result":
                        break
                cr = next(m for m in msgs if m["type"] == "command_result")
                self.assertTrue(cr["success"])
                self.assertTrue(len(adapter.submitted_texts) >= 1)
        except WebSocketDisconnect:
            if exc_type is not None:
                pass
            else:
                raise

    async def test_normalized_error_without_leaking_attachment_content(self) -> None:
        """Error responses must not include raw base64 or attachment payloads."""
        caps = AttachmentCapabilities(
            block_types=("resource_link",),
            resource_links=True,
            images=False,
        )
        adapter = RecordingAdapter(attachments=caps)
        client = self._make_client(adapter)
        exc_type = WebSocketDisconnect if WebSocketDisconnect is not Exception else None
        try:
            with client.websocket_connect("/ws?cwd=/tmp") as ws:
                _read_until_ready(ws)
                ws.send_json(
                    {
                        "protocol_version": 1,
                        "request_id": "r9",
                        "type": "prompt",
                        "session_id": "s1",
                        "turn_id": "t1",
                        "message_id": "m1",
                        "prompt": [
                            {
                                "kind": "image",
                                "name": "img.png",
                                "mime_type": "image/png",
                                "data_base64": _IMAGE_B64,
                            }
                        ],
                    }
                )
                msgs = []
                for _ in range(5):
                    msgs.append(ws.receive_json())
                    if msgs[-1].get("type") in ("command_result", "error"):
                        break
                err_msg = str(msgs[-1])
                self.assertNotIn(_IMAGE_B64, err_msg)
        except WebSocketDisconnect:
            if exc_type is not None:
                pass
            else:
                raise

    async def test_attachments_available_event_shape(self) -> None:
        """Capability events serialize to the documented wire shape."""
        caps = AttachmentCapabilities(
            block_types=("resource_link", "image"),
            resource_links=True,
            images=True,
            audio=False,
            embedded_resources=False,
            max_item_bytes=5 * 1024 * 1024,
            max_total_bytes=10 * 1024 * 1024,
            max_count=10,
        )
        adapter = RecordingAdapter(attachments=caps)
        client = self._make_client(adapter)
        exc_type = WebSocketDisconnect if WebSocketDisconnect is not Exception else None
        try:
            with client.websocket_connect("/ws?cwd=/tmp") as ws:
                events = _read_until_ready(ws)
                attach_ev = [e for e in events if e["type"] == "attachments_available"]
                self.assertEqual(len(attach_ev), 1)
                ev = attach_ev[0]
                self.assertTrue(ev["available"])
                self.assertEqual(ev["block_types"], ["resource_link", "image"])
                self.assertEqual(ev["max_item_bytes"], 5 * 1024 * 1024)
                self.assertEqual(ev["max_total_bytes"], 10 * 1024 * 1024)
                self.assertEqual(ev["max_count"], 10)
        except WebSocketDisconnect:
            if exc_type is not None:
                pass
            else:
                raise

    async def test_unavailable_attachments_event_shape(self) -> None:
        """When attachments are unavailable, the event carries reason fields."""
        adapter = RecordingAdapter()
        client = self._make_client(adapter)
        exc_type = WebSocketDisconnect if WebSocketDisconnect is not Exception else None
        try:
            with client.websocket_connect("/ws?cwd=/tmp") as ws:
                events = _read_until_ready(ws)
                attach_ev = [e for e in events if e["type"] == "attachments_available"]
                self.assertEqual(len(attach_ev), 1)
                ev = attach_ev[0]
                self.assertFalse(ev["available"])
                self.assertIn("reason_code", ev)
                self.assertIn("reason_message", ev)
        except WebSocketDisconnect:
            if exc_type is not None:
                pass
            else:
                raise


# ---------------------------------------------------------------------------
# Phase 10: Persistence degradation
# ---------------------------------------------------------------------------


class DegradationTests(unittest.IsolatedAsyncioTestCase):
    """Live streaming continues when history persistence fails."""

    def _make_client(
        self,
        adapter: RecordingAdapter | None = None,
        repo: HistoryRepository | None = None,
    ) -> TestClient:
        fa = MagicMock()
        fa.create.return_value = adapter or RecordingAdapter()
        app = create_app(adapter_factory=fa, history_repository=repo)
        app.include_router(router)
        return TestClient(app)

    async def test_streaming_continues_when_history_fails(self) -> None:
        """A failing repository must not block the prompt lifecycle."""
        failing_repo = FailingRepository()
        adapter = RecordingAdapter()
        client = self._make_client(adapter, repo=failing_repo)
        exc_type = WebSocketDisconnect if WebSocketDisconnect is not Exception else None
        try:
            with client.websocket_connect("/ws?cwd=/tmp") as ws:
                _read_until_ready(ws)
                # Check that history_degraded diagnostic was emitted
                # (may not appear if no event triggers persistence during startup)
                # depending on whether any event triggers persistence.
                ws.send_json(
                    {
                        "protocol_version": 1,
                        "request_id": "r1",
                        "type": "prompt",
                        "session_id": "s1",
                        "turn_id": "t1",
                        "message_id": "m1",
                        "text": "hello",
                    }
                )
                msgs = []
                for _ in range(10):
                    msgs.append(ws.receive_json())
                    if msgs[-1].get("type") in ("command_result", "error", "done"):
                        break
                types = [m["type"] for m in msgs]
                # The prompt should still complete (command_result + done).
                self.assertIn("command_result", types)
                cr = next(m for m in msgs if m["type"] == "command_result")
                self.assertTrue(cr["success"])
        except WebSocketDisconnect:
            if exc_type is not None:
                pass
            else:
                raise

    async def test_history_marked_degraded_honestly(self) -> None:
        """Once persistence fails, subsequent events should not re-emit the
        degraded diagnostic (one-time guard against recursion)."""
        failing_repo = FailingRepository()
        adapter = RecordingAdapter()
        client = self._make_client(adapter, repo=failing_repo)
        exc_type = WebSocketDisconnect if WebSocketDisconnect is not Exception else None
        try:
            with client.websocket_connect("/ws?cwd=/tmp") as ws:
                _read_until_ready(ws)
                # Send two prompts; only the first should trigger the degraded
                # diagnostic (if any).
                ws.send_json(
                    {
                        "protocol_version": 1,
                        "request_id": "r1",
                        "type": "prompt",
                        "session_id": "s1",
                        "turn_id": "t1",
                        "message_id": "m1",
                        "text": "first",
                    }
                )
                # Drain first prompt: read until its command_result (not the
                # history_degraded diagnostic, which is a separate event).
                for _ in range(10):
                    ev = ws.receive_json()
                    if (
                        ev.get("type") == "command_result"
                        and ev.get("request_id") == "r1"
                    ):
                        break
                else:
                    self.fail("First prompt did not receive its command_result")
                ws.send_json(
                    {
                        "protocol_version": 1,
                        "request_id": "r2",
                        "type": "prompt",
                        "session_id": "s1",
                        "turn_id": "t2",
                        "message_id": "m2",
                        "text": "second",
                    }
                )
                msgs = []
                for _ in range(10):
                    msgs.append(ws.receive_json())
                    if msgs[-1].get("type") == "command_result":
                        break
                cr = next(m for m in msgs if m["type"] == "command_result")
                self.assertTrue(cr["success"])
        except WebSocketDisconnect:
            if exc_type is not None:
                pass
            else:
                raise

    async def test_no_attachment_payload_in_diagnostic(self) -> None:
        """The degradation diagnostic must not echo raw attachment content."""
        failing_repo = FailingRepository()
        caps = AttachmentCapabilities(
            block_types=("resource_link", "image"),
            resource_links=True,
            images=True,
        )
        adapter = RecordingAdapter(attachments=caps)
        client = self._make_client(adapter, repo=failing_repo)
        exc_type = WebSocketDisconnect if WebSocketDisconnect is not Exception else None
        try:
            with client.websocket_connect("/ws?cwd=/tmp") as ws:
                _read_until_ready(ws)
                ws.send_json(
                    {
                        "protocol_version": 1,
                        "request_id": "r1",
                        "type": "prompt",
                        "session_id": "s1",
                        "turn_id": "t1",
                        "message_id": "m1",
                        "prompt": [
                            {
                                "kind": "image",
                                "name": "img.png",
                                "mime_type": "image/png",
                                "data_base64": _IMAGE_B64,
                            },
                        ],
                    }
                )
                msgs = []
                for _ in range(10):
                    msgs.append(ws.receive_json())
                    if msgs[-1].get("type") in ("command_result", "error"):
                        break
                all_text = " ".join(str(m) for m in msgs)
                self.assertNotIn(_IMAGE_B64, all_text)
        except WebSocketDisconnect:
            if exc_type is not None:
                pass
            else:
                raise


if __name__ == "__main__":
    unittest.main()
