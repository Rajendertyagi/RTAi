"""Explicit stream-drop and turn-lifecycle tests for the server adapter.

Drives ``_consume_events`` directly with a scripted SSE source (no OpenCode
process, no network). Verifies that an unexpected end-of-stream fails the turn
exactly once with the correct benchmark reason, while expected terminal markers
(disposed / idle) do not produce a false stream-drop error.
"""

from __future__ import annotations

import json
import types
import unittest
from collections.abc import AsyncIterator
from typing import Any

from app.agents.opencode.server_adapter import OpenCodeServerAdapter


class RecordingBenchmark:
    """Minimal benchmark spy recording mark/fail calls."""

    def __init__(self) -> None:
        self.marks: list[str] = []
        self.failures: list[str] = []

    def mark(self, name: str) -> None:
        self.marks.append(name)

    def fail(self, reason: str) -> None:
        self.failures.append(reason)

    def set_runtime_id(self, key: str, value: str) -> None:
        pass


def sse_lines_from(payloads: list[dict[str, object]]) -> list[str]:
    return [f"data: {json.dumps(p)}\n\n" for p in payloads]


def _async_emit(emitted: list) -> object:
    """Build an async emit callback compatible with the adapter's await."""
    async def emit(event: object) -> None:
        emitted.append(event)

    return emit


class ScriptedSseHttp:
    """Fake HTTP whose stream_lines yields scripted SSE lines then ends.

    Each scripted entry is a full SSE event (e.g. "data: {...}\\n\\n"); the
    generator splits them into individual lines so parse_sse_events sees the
    blank-line dispatch markers it expects.
    """

    def __init__(self, lines: list[str]) -> None:
        self._lines = lines
        self.stream_calls = 0

    async def request(self, method: str, url: str, **kwargs: object) -> object:
        raise AssertionError("request() should not be called in stream tests")

    def stream_lines(self, url: str, **kwargs: object) -> AsyncIterator[str]:
        self.stream_calls += 1
        text = "".join(self._lines)

        async def gen() -> AsyncIterator[str]:
            for line in text.split("\n"):
                yield line

        return gen()


def _dummy_plan() -> object:
    return types.SimpleNamespace(base_url="http://127.0.0.1:1")


def _configure(adapter: OpenCodeServerAdapter, session_id: str, emitted: list,
               benchmark: RecordingBenchmark, awaiting_idle: bool) -> None:
    adapter._session_id = session_id
    adapter._emit = _async_emit(emitted)
    adapter._awaiting_idle = awaiting_idle
    adapter._plan = None
    adapter._benchmark = benchmark


class TestStreamDrop(unittest.IsolatedAsyncioTestCase):
    async def test_unexpected_eof_fails_turn_once_with_stream_dropped(self) -> None:
        adapter = OpenCodeServerAdapter(
            http=ScriptedSseHttp([]), launcher=_NoopLauncher(), opencode_bin="fake"
        )
        emitted: list[dict[str, Any]] = []
        benchmark = RecordingBenchmark()
        _configure(adapter, "ses-own", emitted, benchmark, awaiting_idle=True)
        http = ScriptedSseHttp(
            sse_lines_from(
                [
                    {
                        "type": "message.part.updated",
                        "properties": {
                            "part": {"sessionID": "ses-own", "id": "p1"},
                            "delta": "hello",
                        },
                    }
                    # No session.idle and no server.instance.disposed => drop.
                ]
            )
        )
        adapter._http = http
        await adapter._consume_events(_dummy_plan())

        errors = [e for e in emitted if e.get("type") == "error"]
        self.assertEqual(len(errors), 1, f"expected exactly one error, got {emitted}")
        self.assertIn("terminated", errors[0]["message"].lower())
        self.assertNotIn(
            {"type": "done"}, [{"type": e.get("type")} for e in emitted]
        )
        self.assertEqual(benchmark.failures, ["stream_dropped"])
        # No silent reconnect: the stream source was consumed exactly once.
        self.assertEqual(http.stream_calls, 1)

    async def test_disposed_does_not_false_trigger_stream_drop(self) -> None:
        adapter = OpenCodeServerAdapter(
            http=ScriptedSseHttp([]), launcher=_NoopLauncher(), opencode_bin="fake"
        )
        emitted: list[dict[str, Any]] = []
        benchmark = RecordingBenchmark()
        # Not awaiting a turn: a clean disposal must not look like a failure.
        _configure(adapter, "ses-own", emitted, benchmark, awaiting_idle=False)
        http = ScriptedSseHttp(
            sse_lines_from([{"type": "server.instance.disposed", "properties": {}}])
        )
        adapter._http = http
        await adapter._consume_events(_dummy_plan())

        self.assertEqual(emitted, [])
        self.assertNotIn("stream_dropped", benchmark.failures)

    async def test_normal_idle_completes_cleanly(self) -> None:
        adapter = OpenCodeServerAdapter(
            http=ScriptedSseHttp([]), launcher=_NoopLauncher(), opencode_bin="fake"
        )
        emitted: list[dict[str, Any]] = []
        benchmark = RecordingBenchmark()
        _configure(adapter, "ses-own", emitted, benchmark, awaiting_idle=True)
        http = ScriptedSseHttp(
            sse_lines_from(
                [
                    {
                        "type": "message.part.updated",
                        "properties": {
                            "part": {"sessionID": "ses-own", "id": "p1"},
                            "delta": "hi",
                        },
                    },
                    {"type": "session.idle", "properties": {"sessionID": "ses-own"}},
                ]
            )
        )
        adapter._http = http
        await adapter._consume_events(_dummy_plan())

        types_seen = [e.get("type") for e in emitted]
        self.assertIn("delta", types_seen)
        self.assertIn("done", types_seen)
        self.assertNotIn("error", types_seen)
        self.assertNotIn("stream_dropped", benchmark.failures)


class _NoopLauncher:
    async def launch(self, plan: object) -> tuple[object, object]:
        raise AssertionError("launcher must not be used in stream tests")


if __name__ == "__main__":
    unittest.main()
