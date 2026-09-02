"""Permanent, production-safe diagnostics recorder.

Proves Part 3: a bounded ring buffer, a single shared event-name vocabulary,
and a sanitizer that refuses prompt/model/tool/output/path/credential content
so no sensitive data ever reaches the UI diagnostics panel.
"""

from __future__ import annotations

import unittest

from app.diagnostics import (
    EVENT,
    MAX_EVENTS,
    DiagnosticsRecorder,
)


class DiagnosticsRecorderTests(unittest.IsolatedAsyncioTestCase):
    def test_event_vocabulary_is_stable_and_shared(self) -> None:
        # The UI consumes these exact event names; they must be centrally defined.
        self.assertEqual(EVENT["ACP_CONFIG_OPTION_SENT"], "acp.config_option.sent")
        self.assertEqual(EVENT["PERMISSION_RECEIVED"], "permission.received")
        self.assertEqual(EVENT["PERMISSION_PROTOCOL_ERROR"], "permission.protocol_error")
        self.assertEqual(EVENT["STATE_PROJECTED"], "state.projected")
        self.assertEqual(EVENT["SESSION_CLOSED"], "session.closed")
        # Every value is a non-empty dotted string.
        for v in EVENT.values():
            self.assertIsInstance(v, str)
            self.assertTrue(v)

    def test_ring_buffer_is_bounded_at_max_events(self) -> None:
        rec = DiagnosticsRecorder()
        for i in range(MAX_EVENTS + 50):
            rec.record(EVENT["TOOL_START"], "info", tool=f"t{i}")
        snap = rec.snapshot()
        self.assertEqual(len(snap), MAX_EVENTS)
        # Oldest dropped, newest retained (chronological, oldest first).
        self.assertEqual(snap[-1]["tool"], "t" + str(MAX_EVENTS + 49))
        self.assertEqual(snap[0]["tool"], "t" + str(50))

    def test_sensitive_keys_are_dropped(self) -> None:
        rec = DiagnosticsRecorder()
        rec.record(
            EVENT["PROMPT_STARTED"],
            "info",
            # safe scalar correlation id
            session="abc123",
            # sensitive keys that must never be recorded
            text="secret user prompt",
            prompt="secret user prompt",
            output="model output",
            content="content blob",
            args={"cmd": "rm -rf /"},
            result="tool result",
            path="/home/secret",
            token="sk-123456",
            file="creds.txt",
        )
        snap = rec.snapshot()
        self.assertEqual(len(snap), 1)
        entry = snap[0]
        self.assertEqual(entry["session"], "abc123")
        for banned in (
            "text",
            "prompt",
            "output",
            "content",
            "args",
            "result",
            "path",
            "token",
            "file",
        ):
            self.assertNotIn(banned, entry, f"sensitive key {banned} leaked")

    def test_long_strings_are_truncated(self) -> None:
        rec = DiagnosticsRecorder()
        rec.record(EVENT["TOOL_START"], "info", note="x" * 500)
        entry = rec.snapshot()[0]
        self.assertLessEqual(len(entry["note"]), 64)

    def test_invalid_level_is_normalized(self) -> None:
        rec = DiagnosticsRecorder()
        rec.record(EVENT["TOOL_RESULT"], "verbose", tool="t1")
        self.assertEqual(rec.snapshot()[0]["level"], "info")

    def test_snapshot_is_a_copy(self) -> None:
        rec = DiagnosticsRecorder()
        rec.record(EVENT["STREAM_COMPLETED"], "info")
        outside = rec.snapshot()
        outside.append({"tamper": True})
        # Internal buffer unaffected by mutating the returned list.
        self.assertEqual(len(rec.snapshot()), 1)


if __name__ == "__main__":
    unittest.main()
