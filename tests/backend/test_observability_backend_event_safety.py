"""Backend observability event payload safety (Task 3).

Exercises the REAL diagnostics emission paths for the three new events and
proves each recorded event carries ONLY its permitted safe scalar fields and
NEVER any sensitive content (text, path, id, tool name, raw result, or diff
contents).

- ``tool.content.mapped`` -> contentKind, blockCount
- ``tool.result.projected`` -> resultKind, hasCodeDiff, isError, status
- ``permission.projected`` -> pending, hasOptions, status

The backend DiagnosticsRecorder already sanitizes sensitive keys; these tests
add event-specific guards proving the emission call sites themselves never
hand the recorder anything outside the approved schema.
"""

from __future__ import annotations

import asyncio
import unittest
from typing import Any

from app.agents.acp.session import AcpSession
from app.diagnostics import EVENT, DiagnosticsRecorder
from app.transport.assistant.acp_state_projector import AcpStateProjector


def _find_event(snapshot: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for entry in snapshot:
        if entry.get("event") == name:
            return entry
    return None


class ToolContentMappedPayloadTests(unittest.TestCase):
    def _record_for(self, dumped: dict[str, Any]) -> dict[str, Any]:
        rec = DiagnosticsRecorder()
        sess = AcpSession()
        sess.diag = rec  # type: ignore[attr-defined]
        sess._emit = None  # type: ignore[attr-defined]
        asyncio.run(sess._emit_tool_event(dumped))
        return _find_event(rec.snapshot(), EVENT["TOOL_CONTENT_MAPPED"])

    def test_only_permitted_fields_present(self) -> None:
        entry = self._record_for(
            {
                "sessionUpdate": "tool_call",
                "toolCallId": "tc-secret-123",
                "status": "running",
                "title": "fs_read_tool",
                "content": [
                    {
                        "type": "diff",
                        "path": "/home/secret/file.txt",
                        "oldText": "line one\nline two",
                        "newText": "line one\nline two modified",
                    }
                ],
            }
        )
        self.assertIsNotNone(entry)
        self.assertEqual(set(entry.keys()), {"ts", "event", "level", "contentKind", "blockCount"})
        self.assertEqual(entry["contentKind"], "diff")
        self.assertEqual(entry["blockCount"], 1)
        # Sensitive keys must NOT appear in the recorded metadata.
        for banned in ("text", "path", "oldText", "newText", "toolCallId", "title"):
            self.assertNotIn(banned, entry)

    def test_text_content_classified(self) -> None:
        entry = self._record_for(
            {
                "sessionUpdate": "tool_call",
                "toolCallId": "tc-1",
                "status": "running",
                "content": [{"type": "content", "text": "hidden prompt content"}],
            }
        )
        self.assertIsNotNone(entry)
        self.assertEqual(entry["contentKind"], "text")
        self.assertEqual(entry["blockCount"], 1)
        self.assertNotIn("text", entry)


class ToolResultProjectedPayloadTests(unittest.IsolatedAsyncioTestCase):
    def _make_projector(self, tool_call_id: str) -> tuple[AcpStateProjector, DiagnosticsRecorder]:
        rec = DiagnosticsRecorder()
        ctrl: dict[str, Any] = {
            "messages": [
                {
                    "role": "assistant",
                    "parts": [
                        {"type": "tool-call", "toolCallId": tool_call_id, "toolName": "fs"}
                    ],
                }
            ],
            "status": "running",
        }
        proj = AcpStateProjector(ctrl, session_key="sess1")  # type: ignore[arg-type]
        proj.diagnostics = rec  # type: ignore[attr-defined]
        return proj, rec

    async def _handle_tool_result(self, content: Any, status: str) -> dict[str, Any] | None:
        proj, rec = self._make_projector("tc-1")
        await proj.handle(
            {
                "type": "tool_result",
                "tool_call_id": "tc-1",
                "status": status,
                "content": content,
            }
        )
        return _find_event(rec.snapshot(), EVENT["TOOL_RESULT_PROJECTED"])

    async def test_only_permitted_fields_diff(self) -> None:
        entry = await self._handle_tool_result(
            [
                {
                    "type": "diff",
                    "path": "/etc/secret",
                    "oldText": "a",
                    "newText": "b",
                }
            ],
            "success",
        )
        self.assertIsNotNone(entry)
        self.assertEqual(
            set(entry.keys()),
            {"ts", "event", "level", "resultKind", "hasCodeDiff", "isError", "status"},
        )
        self.assertEqual(entry["resultKind"], "diff")
        self.assertEqual(entry["hasCodeDiff"], True)
        self.assertEqual(entry["isError"], False)
        self.assertEqual(entry["status"], "complete")
        for banned in ("text", "path", "oldText", "newText", "toolCallId", "toolName"):
            self.assertNotIn(banned, entry)

    async def test_error_status_maps_to_incomplete(self) -> None:
        entry = await self._handle_tool_result(None, "error")
        self.assertIsNotNone(entry)
        self.assertEqual(entry["isError"], True)
        self.assertEqual(entry["status"], "incomplete")
        # No content -> honest "<no result>" string fallback, classified as text.
        self.assertEqual(entry["resultKind"], "text")

    async def test_text_result_classified(self) -> None:
        entry = await self._handle_tool_result(
            [{"type": "content", "text": "private stdout"}], "success"
        )
        self.assertIsNotNone(entry)
        self.assertEqual(entry["resultKind"], "text")
        self.assertEqual(entry["hasCodeDiff"], False)
        self.assertNotIn("text", entry)


class PermissionProjectedPayloadTests(unittest.TestCase):
    def _record_for(self, options: list[dict[str, Any]]) -> dict[str, Any]:
        rec = DiagnosticsRecorder()
        ctrl: dict[str, Any] = {"messages": [], "status": "running"}
        proj = AcpStateProjector(ctrl, session_key="sess1")  # type: ignore[arg-type]
        proj.diagnostics = rec  # type: ignore[attr-defined]
        part: dict[str, Any] = {"type": "tool-call", "toolCallId": "tc-1"}
        proj._attach_approval(
            part,
            {"options": options},
            "perm-secret-999",
        )
        return _find_event(rec.snapshot(), EVENT["PERMISSION_PROJECTED"])

    def test_only_permitted_fields_present(self) -> None:
        entry = self._record_for(
            [{"id": "allow-once", "label": "Allow", "kind": "allow_once"}]
        )
        self.assertIsNotNone(entry)
        self.assertEqual(
            set(entry.keys()),
            {"ts", "event", "level", "pending", "hasOptions", "status"},
        )
        self.assertEqual(entry["pending"], True)
        self.assertEqual(entry["hasOptions"], True)
        self.assertEqual(entry["status"], "requires-action")
        # No id / tool name / option detail leakage.
        for banned in ("id", "toolCallId", "options", "permission_id", "approval"):
            self.assertNotIn(banned, entry)

    def test_no_options_yields_has_options_false(self) -> None:
        entry = self._record_for([])
        self.assertIsNotNone(entry)
        self.assertEqual(entry["hasOptions"], False)
        self.assertEqual(entry["pending"], True)
        self.assertEqual(entry["status"], "requires-action")


if __name__ == "__main__":
    unittest.main()
