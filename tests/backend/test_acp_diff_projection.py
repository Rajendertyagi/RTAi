"""Diff display and tool-error status projection regression tests.

Verifies the two new projector helpers added for official CodeDiff rendering
and the pinned tool-call status for failed tools:

- ``_diff_display_payload``: pure ACP diff block -> CodeDiff props.
- ``_attach_diff_display``: attaches the derived payload alongside raw ACP
  values without mutating the original block content.
- Tool-error status projection on ``tool_result``: ``isError`` stays set and
  ``status`` is exactly ``{"type": "incomplete", "reason": "error"}``.
- Non-diff tool results are unchanged — no CodeDiff payload is attached.
- Malformed/non-diff structured results receive no CodeDiff payload.

All tests drive the real projector helpers and the real ``AcpStateProjector``
path, not reimplemented copies.
"""

from __future__ import annotations

import asyncio
import unittest
from typing import Any

from app.transport.assistant.acp_state_projector import (
    AcpStateProjector,
    _attach_diff_display,
    _diff_display_payload,
)


# ---------------------------------------------------------------------------
# Pure-helper tests
# ---------------------------------------------------------------------------

class DiffDisplayPayloadTests(unittest.TestCase):
    """Direct unit tests for ``_diff_display_payload``."""

    def test_equal_lines_yields_context_only(self) -> None:
        block = {
            "type": "diff",
            "path": "src/app.ts",
            "oldText": "hello\nworld",
            "newText": "hello\nworld",
        }
        payload = _diff_display_payload(block)
        self.assertEqual(payload["filename"], "src/app.ts")
        self.assertEqual(payload["additions"], 0)
        self.assertEqual(payload["deletions"], 0)
        self.assertEqual(payload["cycle"], 0)
        self.assertEqual(len(payload["lines"]), 2)
        for line in payload["lines"]:
            self.assertEqual(line["kind"], "context")

    def test_insertion_yields_added_lines(self) -> None:
        block = {
            "type": "diff",
            "path": "src/app.ts",
            "oldText": "hello",
            "newText": "hello\nworld",
        }
        payload = _diff_display_payload(block)
        self.assertEqual(payload["additions"], 1)
        self.assertEqual(payload["deletions"], 0)
        kinds = [l["kind"] for l in payload["lines"]]
        self.assertIn("added", kinds)
        self.assertIn("context", kinds)

    def test_deletion_yields_removed_lines(self) -> None:
        block = {
            "type": "diff",
            "path": "src/app.ts",
            "oldText": "hello\nworld",
            "newText": "hello",
        }
        payload = _diff_display_payload(block)
        self.assertEqual(payload["additions"], 0)
        self.assertEqual(payload["deletions"], 1)
        kinds = [l["kind"] for l in payload["lines"]]
        self.assertIn("removed", kinds)
        self.assertIn("context", kinds)

    def test_replace_yields_removed_then_added(self) -> None:
        block = {
            "type": "diff",
            "path": "src/app.ts",
            "oldText": "old line",
            "newText": "new line",
        }
        payload = _diff_display_payload(block)
        self.assertEqual(payload["additions"], 1)
        self.assertEqual(payload["deletions"], 1)
        # replace op: removed lines come before added lines
        removed_indices = [i for i, l in enumerate(payload["lines"]) if l["kind"] == "removed"]
        added_indices = [i for i, l in enumerate(payload["lines"]) if l["kind"] == "added"]
        self.assertLess(max(removed_indices), min(added_indices))

    def test_additions_deletions_equal_emitted_line_counts(self) -> None:
        """Invariants: additions == count of 'added' lines, deletions == count of 'removed' lines."""
        block = {
            "type": "diff",
            "path": "src/app.ts",
            "oldText": "a\nb\nc",
            "newText": "a\nx\nc\ny",
        }
        payload = _diff_display_payload(block)
        added_count = sum(1 for l in payload["lines"] if l["kind"] == "added")
        removed_count = sum(1 for l in payload["lines"] if l["kind"] == "removed")
        self.assertEqual(payload["additions"], added_count)
        self.assertEqual(payload["deletions"], removed_count)

    def test_missing_path_defaults_to_unnamed_file(self) -> None:
        block = {"type": "diff", "oldText": "a", "newText": "b"}
        payload = _diff_display_payload(block)
        self.assertEqual(payload["filename"], "(unnamed file)")

    def test_empty_texts_yields_empty_lines(self) -> None:
        block = {"type": "diff", "path": "f.ts", "oldText": "", "newText": ""}
        payload = _diff_display_payload(block)
        self.assertEqual(payload["lines"], [])
        self.assertEqual(payload["additions"], 0)
        self.assertEqual(payload["deletions"], 0)

    def test_raw_block_preserved_unchanged(self) -> None:
        """_diff_display_payload must not mutate the input block."""
        block = {
            "type": "diff",
            "path": "src/app.ts",
            "oldText": "hello",
            "newText": "hello",
        }
        original = dict(block)
        _diff_display_payload(block)
        self.assertEqual(block, original)
        self.assertNotIn("diff", block)


class AttachDiffDisplayTests(unittest.TestCase):
    """Direct unit tests for ``_attach_diff_display``."""

    def test_single_diff_block_gains_payload(self) -> None:
        result = {"type": "diff", "path": "src/app.ts", "oldText": "a", "newText": "b"}
        _attach_diff_display(result)
        self.assertIn("diff", result)
        self.assertIsInstance(result["diff"], dict)
        self.assertEqual(result["diff"]["filename"], "src/app.ts")
        # Raw ACP fields preserved
        self.assertEqual(result["type"], "diff")
        self.assertEqual(result["path"], "src/app.ts")
        self.assertEqual(result["oldText"], "a")
        self.assertEqual(result["newText"], "b")

    def test_list_with_diff_block_gains_payload(self) -> None:
        result = [
            {"type": "content", "text": "header"},
            {"type": "diff", "path": "src/app.ts", "oldText": "a", "newText": "b"},
        ]
        _attach_diff_display(result)
        self.assertEqual(len(result), 2)
        self.assertNotIn("diff", result[0])
        self.assertIn("diff", result[1])
        self.assertEqual(result[1]["diff"]["filename"], "src/app.ts")

    def test_non_diff_block_untouched(self) -> None:
        result = {"type": "content", "text": "hello"}
        _attach_diff_display(result)
        self.assertNotIn("diff", result)
        self.assertEqual(result, {"type": "content", "text": "hello"})

    def test_idempotent_no_double_payload(self) -> None:
        """Calling twice must not overwrite the existing payload."""
        result = {"type": "diff", "path": "f.ts", "oldText": "a", "newText": "b"}
        _attach_diff_display(result)
        first_payload = dict(result["diff"])
        _attach_diff_display(result)
        self.assertEqual(result["diff"], first_payload)

    def test_string_result_ignored(self) -> None:
        _attach_diff_display("just a string")

    def test_none_result_ignored(self) -> None:
        _attach_diff_display(None)

    def test_number_result_ignored(self) -> None:
        _attach_diff_display(42)

    def test_mixed_list_partial_payload(self) -> None:
        result = [
            {"type": "content", "text": "before"},
            {"type": "diff", "path": "a.ts", "oldText": "x", "newText": "y"},
            {"type": "content", "text": "after"},
            {"type": "diff", "path": "b.ts", "oldText": "p", "newText": "q"},
        ]
        _attach_diff_display(result)
        self.assertNotIn("diff", result[0])
        self.assertIn("diff", result[1])
        self.assertNotIn("diff", result[2])
        self.assertIn("diff", result[3])
        self.assertEqual(result[1]["diff"]["filename"], "a.ts")
        self.assertEqual(result[3]["diff"]["filename"], "b.ts")


# ---------------------------------------------------------------------------
# Projector-level integration tests
# ---------------------------------------------------------------------------

class _StubController:
    """Minimal stand-in for RunController."""

    def __init__(self, state: dict) -> None:
        self.state = state

    def flush(self) -> None:
        pass

    def append_state_text(self, *args: Any, **kwargs: Any) -> None:
        pass


def _projector() -> tuple[_StubController, AcpStateProjector]:
    ctrl = _StubController({"messages": [], "status": "running"})
    proj = AcpStateProjector(ctrl, session_key="sess-1")
    return ctrl, proj


def _tool_parts(ctrl: _StubController) -> list[dict[str, Any]]:
    parts = []
    for msg in ctrl.state.get("messages", []):
        for part in msg.get("parts", []):
            if isinstance(part, dict) and part.get("type") == "tool-call":
                parts.append(part)
    return parts


class ToolErrorProjectionTests(unittest.IsolatedAsyncioTestCase):
    """Verify the pinned tool-call status on error tool_result events."""

    async def test_error_sets_iserror_and_incomplete_status(self) -> None:
        ctrl, proj = _projector()
        await proj.handle({
            "type": "tool_start",
            "tool_call_id": "tc-1",
            "toolName": "bash",
            "raw_input": {"command": "rm -rf /"},
        })
        await proj.handle({
            "type": "tool_result",
            "tool_call_id": "tc-1",
            "status": "error",
            "content": None,
        })
        parts = _tool_parts(ctrl)
        self.assertEqual(len(parts), 1)
        part = parts[0]
        self.assertTrue(part.get("isError"))
        self.assertEqual(part.get("status"), {"type": "incomplete", "reason": "error"})

    async def test_error_on_existing_part_sets_status(self) -> None:
        ctrl, proj = _projector()
        await proj.handle({
            "type": "tool_start",
            "tool_call_id": "tc-1",
            "toolName": "bash",
            "raw_input": {"command": "ls"},
        })
        await proj.handle({
            "type": "tool_result",
            "tool_call_id": "tc-1",
            "status": "error",
            "content": None,
        })
        parts = _tool_parts(ctrl)
        part = parts[0]
        self.assertTrue(part.get("isError"))
        self.assertEqual(part.get("status"), {"type": "incomplete", "reason": "error"})

    async def test_success_clears_error_and_no_status(self) -> None:
        ctrl, proj = _projector()
        await proj.handle({
            "type": "tool_start",
            "tool_call_id": "tc-1",
            "toolName": "bash",
            "raw_input": {"command": "ls"},
        })
        await proj.handle({
            "type": "tool_result",
            "tool_call_id": "tc-1",
            "status": "success",
            "content": [{"type": "content", "text": "file.txt"}],
        })
        parts = _tool_parts(ctrl)
        part = parts[0]
        self.assertFalse(part.get("isError"))
        # Success does not set status
        self.assertNotIn("status", part)

    async def test_error_no_invented_error_message(self) -> None:
        """When error_message is absent, no text is injected into status."""
        ctrl, proj = _projector()
        await proj.handle({
            "type": "tool_start",
            "tool_call_id": "tc-1",
            "toolName": "bash",
            "raw_input": {"command": "fail"},
        })
        await proj.handle({
            "type": "tool_result",
            "tool_call_id": "tc-1",
            "status": "error",
            "content": None,
        })
        parts = _tool_parts(ctrl)
        part = parts[0]
        status = part.get("status")
        self.assertIsNotNone(status)
        self.assertEqual(status["type"], "incomplete")
        self.assertEqual(status["reason"], "error")
        # No error text field invented
        self.assertNotIn("error", status)


class DiffProjectionTests(unittest.IsolatedAsyncioTestCase):
    """Verify diff blocks in tool_result get the CodeDiff display payload."""

    async def test_diff_block_preserves_raw_and_gains_diff_payload(self) -> None:
        ctrl, proj = _projector()
        await proj.handle({
            "type": "tool_start",
            "tool_call_id": "tc-1",
            "toolName": "edit_file",
            "raw_input": {"path": "src/app.ts"},
        })
        await proj.handle({
            "type": "tool_result",
            "tool_call_id": "tc-1",
            "status": "success",
            "content": [
                {
                    "type": "diff",
                    "path": "src/app.ts",
                    "oldText": "old line",
                    "newText": "new line",
                }
            ],
        })
        parts = _tool_parts(ctrl)
        part = parts[0]
        result = part.get("result")
        self.assertIsInstance(result, dict)
        # Raw ACP fields preserved
        self.assertEqual(result["type"], "diff")
        self.assertEqual(result["path"], "src/app.ts")
        self.assertEqual(result["oldText"], "old line")
        self.assertEqual(result["newText"], "new line")
        # CodeDiff display payload attached
        self.assertIn("diff", result)
        diff_payload = result["diff"]
        self.assertEqual(diff_payload["filename"], "src/app.ts")
        self.assertEqual(diff_payload["additions"], 1)
        self.assertEqual(diff_payload["deletions"], 1)
        self.assertEqual(diff_payload["cycle"], 0)
        self.assertEqual(len(diff_payload["lines"]), 2)

    async def test_text_result_unaffected(self) -> None:
        ctrl, proj = _projector()
        await proj.handle({
            "type": "tool_start",
            "tool_call_id": "tc-1",
            "toolName": "read_file",
            "raw_input": {"path": "src/app.ts"},
        })
        await proj.handle({
            "type": "tool_result",
            "tool_call_id": "tc-1",
            "status": "success",
            "content": [{"type": "content", "text": "file contents"}],
        })
        parts = _tool_parts(ctrl)
        part = parts[0]
        result = part.get("result")
        self.assertIsInstance(result, str)
        self.assertEqual(result, "file contents")
        # No diff payload on text result
        self.assertNotIn("diff", part)

    async def test_malformed_diff_no_payload(self) -> None:
        """Non-diff structured results must not receive a CodeDiff payload."""
        ctrl, proj = _projector()
        await proj.handle({
            "type": "tool_start",
            "tool_call_id": "tc-1",
            "toolName": "some_tool",
            "raw_input": {},
        })
        await proj.handle({
            "type": "tool_result",
            "tool_call_id": "tc-1",
            "status": "success",
            "content": [{"type": "json", "data": {"key": "value"}}],
        })
        parts = _tool_parts(ctrl)
        part = parts[0]
        result = part.get("result")
        self.assertIsInstance(result, dict)
        self.assertNotIn("diff", result)

    async def test_multi_block_with_one_diff(self) -> None:
        ctrl, proj = _projector()
        await proj.handle({
            "type": "tool_start",
            "tool_call_id": "tc-1",
            "toolName": "edit_file",
            "raw_input": {},
        })
        await proj.handle({
            "type": "tool_result",
            "tool_call_id": "tc-1",
            "status": "success",
            "content": [
                {"type": "content", "text": "Done editing"},
                {
                    "type": "diff",
                    "path": "src/app.ts",
                    "oldText": "a",
                    "newText": "b",
                },
            ],
        })
        parts = _tool_parts(ctrl)
        part = parts[0]
        result = part.get("result")
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 2)
        # First block: text, no diff payload
        self.assertNotIn("diff", result[0])
        # Second block: diff, has diff payload
        self.assertIn("diff", result[1])
        self.assertEqual(result[1]["diff"]["filename"], "src/app.ts")


if __name__ == "__main__":
    unittest.main()
