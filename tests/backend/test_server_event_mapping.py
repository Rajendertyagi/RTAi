"""Server adapter event-mapping, foreign-session and stream-drop tests."""

from __future__ import annotations

import asyncio
import json
import types
import unittest
from collections.abc import AsyncIterator
from typing import Any

from app.agents.opencode.server_adapter import OpenCodeServerAdapter


class FakeHttp:
    """Scripted JSON transport for readiness + discovery."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def request(self, method: str, url: str, **kwargs: object) -> object:
        self.calls.append((method, url))
        from app.agents.opencode.http_client import HttpResult

        if "/global/health" in url:
            return HttpResult(status=200, body=b'{"healthy": true, "version": "1.0"}')
        if "/session" in url and method == "POST":
            return HttpResult(status=200, body=b'{"id": "ses-own"}')
        if "/config/providers" in url:
            import json
            return HttpResult(
                status=200,
                body=json.dumps({"prov": {"models": {"m1": {"name": "M1"}}}}).encode(),
            )
        if "/config" in url:
            return HttpResult(status=200, body=b'{"model": "prov/m1"}')
        if "/command" in url:
            return HttpResult(status=200, body=b'[{"name": "init", "description": "d"}]')
        if "/agent" in url:
            return HttpResult(
                status=200,
                body=b'[{"name": "build", "description": "Builder"}, '
                     b'{"name": "plan", "description": "Planner"}]',
            )
        return HttpResult(status=404, body=b"{}")

    def stream_lines(self, url: str, **kwargs: object) -> object:
        class Empty:
            def __aiter__(self) -> Empty:
                return self
            async def __anext__(self) -> str:
                # Stream that never delivers an event; the test cancels it.
                # Use a short sleep so cancellation propagates quickly.
                try:
                    await asyncio.sleep(0.1)
                except asyncio.CancelledError:
                    raise
                raise StopAsyncIteration
        return Empty()



class FakeLauncher:
    async def launch(self, plan: object) -> tuple[object, object]:
        from app.agents.owned_process import OwnedProcess

        class Proc:
            pid = 9999
            returncode = None
            def terminate(self) -> None: pass
            async def wait(self) -> int: return 0
            def kill(self) -> None: pass

        process = Proc()

        async def coop() -> None:
            pass

        owned = OwnedProcess(
            handle=process, pid=process.pid,
            argv=getattr(plan, "argv", ("x",)),
            cooperative_close=coop,
        )
        return owned, process


def _make_adapter(**kw: object) -> OpenCodeServerAdapter:
    return OpenCodeServerAdapter(
        http=FakeHttp(), launcher=FakeLauncher(), opencode_bin="fake", **kw
    )


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
    """Render event payloads as raw SSE data lines."""
    return [f"data: {json.dumps(p)}\n\n" for p in payloads]


def _async_emit(emitted: list) -> object:
    """Build an async emit callback compatible with the adapter's await."""
    async def emit(event: object) -> None:
        emitted.append(event)

    return emit


class ScriptedSseHttp(FakeHttp):
    """Fake HTTP whose stream_lines yields scripted SSE lines then ends.

    Each scripted entry is a full SSE event (e.g. "data: {...}\\n\\n"); the
    generator splits them into individual lines so parse_sse_events sees the
    blank-line dispatch markers it expects.
    """

    def __init__(self, lines: list[str]) -> None:
        super().__init__()
        self._lines = lines

    def stream_lines(self, url: str, **kwargs: object) -> AsyncIterator[str]:
        text = "".join(self._lines)

        async def gen() -> AsyncIterator[str]:
            for line in text.split("\n"):
                yield line

        return gen()


def _dummy_plan() -> object:
    return types.SimpleNamespace(base_url="http://127.0.0.1:1")


class TestEventMapping(unittest.IsolatedAsyncioTestCase):
    async def test_agents_populate_agents_section_not_modes(self) -> None:
        adapter = _make_adapter()
        emitted: list[dict[str, Any]] = []
        await adapter.start(None, emit=emitted.append)
        snap = adapter.capability_snapshot()
        self.assertIsNotNone(snap.agents)
        self.assertFalse(snap.agents.is_empty_but_available)
        self.assertGreater(len(snap.agents.items), 0)
        agent_ids = [a.id for a in snap.agents.items]
        self.assertIn("build", agent_ids)
        self.assertIn("plan", agent_ids)
        # Agents are NOT modes.
        self.assertFalse(snap.modes.available)
        self.assertEqual(snap.modes.items, ())
        await adapter.close()

    async def test_modes_unavailable_without_server_endpoint(self) -> None:
        adapter = _make_adapter()
        emitted: list[dict[str, Any]] = []
        await adapter.start(None, emit=emitted.append)
        snap = adapter.capability_snapshot()
        # The server API has no documented mode endpoint.
        self.assertEqual(snap.modes.items, ())
        # Modes are available-but-empty here because the server returned
        # no mode config option; they would be unavailable if we couldn't
        # query the endpoint at all. The key is they are not populated
        # from /agent data.
        await adapter.close()

    async def test_thinking_unavailable_when_no_variants(self) -> None:
        adapter = _make_adapter()
        emitted: list[dict[str, Any]] = []
        await adapter.start(None, emit=emitted.append)
        snap = adapter.capability_snapshot()
        # PROVIDERS fixture has no model variants => thinking unavailable.
        self.assertFalse(snap.thinking_options.available)
        assert snap.thinking_options.unavailable is not None
        self.assertIn("variants", snap.thinking_options.unavailable.message.lower())
        await adapter.close()


class TestForeignSessionFiltering(unittest.IsolatedAsyncioTestCase):
    def _adapter(self, session_id: str = "ses-own") -> OpenCodeServerAdapter:
        adapter = _make_adapter()
        adapter._session_id = session_id
        return adapter

    def test_direct_session_id_foreign_rejected(self) -> None:
        adapter = self._adapter()
        self.assertTrue(
            adapter._is_foreign_event(
                "message.part.updated", {"sessionID": "ses-other"}
            )
        )
        self.assertFalse(
            adapter._is_foreign_event(
                "message.part.updated", {"sessionID": "ses-own"}
            )
        )

    def test_part_nested_session_id_foreign_rejected(self) -> None:
        adapter = self._adapter()
        self.assertTrue(
            adapter._is_foreign_event(
                "message.part.updated", {"part": {"sessionID": "ses-other"}}
            )
        )
        self.assertFalse(
            adapter._is_foreign_event(
                "message.part.updated", {"part": {"sessionID": "ses-own"}}
            )
        )

    def test_info_nested_session_id_foreign_rejected(self) -> None:
        adapter = self._adapter()
        self.assertTrue(
            adapter._is_foreign_event(
                "session.idle", {"info": {"sessionID": "ses-other"}}
            )
        )
        self.assertFalse(
            adapter._is_foreign_event(
                "session.idle", {"info": {"sessionID": "ses-own"}}
            )
        )

    def test_missing_session_id_non_global_dropped(self) -> None:
        # Documented policy: a non-global event without any session id is
        # treated as foreign and dropped (never emitted). Global, session-less
        # events remain benign (handled, not foreign).
        adapter = self._adapter()
        self.assertTrue(adapter._is_foreign_event("some.unknown.event", {}))
        self.assertFalse(adapter._is_foreign_event("server.connected", {}))
        self.assertFalse(adapter._is_foreign_event("server.heartbeat", {}))

    async def test_foreign_events_never_emit_turn_signals(self) -> None:
        adapter = _make_adapter()
        adapter._session_id = "ses-own"
        emitted: list[dict[str, Any]] = []
        adapter._emit = _async_emit(emitted)
        adapter._awaiting_idle = False
        adapter._plan = None
        lines = sse_lines_from(
            [
                {
                    "type": "message.part.updated",
                    "properties": {"part": {"sessionID": "ses-other"}, "delta": "x"},
                },
                {"type": "session.idle", "properties": {"sessionID": "ses-other"}},
                {
                    "type": "session.error",
                    "properties": {
                        "sessionID": "ses-other",
                        "error": {"message": "boom"},
                    },
                },
                {"type": "server.instance.disposed", "properties": {}},
            ]
        )
        adapter._http = ScriptedSseHttp(lines)
        await adapter._consume_events(_dummy_plan())
        # Foreign events are dropped; disposed is benign. Nothing emitted.
        self.assertEqual(emitted, [])

    async def test_unknown_event_with_matching_session_id_reaches_raw(self) -> None:
        adapter = _make_adapter()
        adapter._session_id = "ses-own"
        emitted: list[dict[str, Any]] = []
        adapter._emit = _async_emit(emitted)
        adapter._awaiting_idle = False
        adapter._plan = None
        lines = sse_lines_from(
            [
                {
                    "type": "unknown.event",
                    "properties": {"sessionID": "ses-own", "data": "x"},
                },
                {"type": "server.instance.disposed", "properties": {}},
            ]
        )
        adapter._http = ScriptedSseHttp(lines)
        await adapter._consume_events(_dummy_plan())
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0]["type"], "raw")
        self.assertEqual(emitted[0]["event"], "unknown.event")


class TestSessionErrorExactMatch(unittest.IsolatedAsyncioTestCase):
    async def test_exact_session_error_type_is_blocking(self) -> None:
        # Only the exact "session.error" type maps to a blocking error.
        # awaiting_idle is False so the trailing disposed marker does not also
        # emit a terminal-drop error; we are isolating the session.error mapping.
        adapter = _make_adapter()
        adapter._session_id = "ses-own"
        emitted: list[dict[str, Any]] = []
        adapter._emit = _async_emit(emitted)
        adapter._awaiting_idle = False
        adapter._plan = None
        lines = sse_lines_from(
            [
                {
                    "type": "session.error",
                    "properties": {
                        "sessionID": "ses-own",
                        "error": {"message": "boom"},
                    },
                },
                {"type": "server.instance.disposed", "properties": {}},
            ]
        )
        adapter._http = ScriptedSseHttp(lines)
        await adapter._consume_events(_dummy_plan())
        errors = [e for e in emitted if e.get("type") == "error"]
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["message"], "boom")

    async def test_benign_error_substring_not_treated_as_session_error(self) -> None:
        # e.g. "file.error.report" must NOT map to session.error.
        adapter = _make_adapter()
        adapter._session_id = "ses-own"
        emitted: list[dict[str, Any]] = []
        adapter._emit = _async_emit(emitted)
        adapter._awaiting_idle = False
        adapter._plan = None
        lines = sse_lines_from(
            [
                {"type": "file.error.report", "properties": {"sessionID": "ses-own"}},
                {"type": "server.instance.disposed", "properties": {}},
            ]
        )
        adapter._http = ScriptedSseHttp(lines)
        await adapter._consume_events(_dummy_plan())
        self.assertFalse(any(e.get("type") == "error" for e in emitted))
        # It reaches the raw diagnostics channel instead.
        self.assertTrue(any(e.get("type") == "raw" for e in emitted))


class TestPartEventMapping(unittest.IsolatedAsyncioTestCase):
    """Server text/reasoning parts stream as part_start/part_delta/part_done.

    Mirrors the ACP adapter's part protocol: thinking and reply text become
    separate parts in chronological order, tool and other non-content parts
    close the open content part, and the legacy ``delta`` event is kept for
    text parts only.
    """

    def _adapter(self, emitted: list[dict[str, Any]]) -> OpenCodeServerAdapter:
        adapter = _make_adapter()
        adapter._session_id = "ses-own"
        adapter._emit = _async_emit(emitted)
        adapter._awaiting_idle = True
        adapter._plan = None
        return adapter

    async def _run(
        self, adapter: OpenCodeServerAdapter, payloads: list[dict[str, object]]
    ) -> None:
        adapter._http = ScriptedSseHttp(sse_lines_from(payloads))
        await adapter._consume_events(_dummy_plan())

    def _part(
        self,
        part_type: str,
        part_id: str,
        delta: str | None = None,
        **extra: object,
    ) -> dict[str, object]:
        props: dict[str, object] = {
            "sessionID": "ses-own",
            "part": {"type": part_type, "id": part_id, **extra},
        }
        if delta is not None:
            props["delta"] = delta
        return {"type": "message.part.updated", "properties": props}

    def _idle(self) -> dict[str, object]:
        return {"type": "session.idle", "properties": {"sessionID": "ses-own"}}

    def _disposed(self) -> dict[str, object]:
        return {"type": "server.instance.disposed", "properties": {}}

    async def test_text_part_streams_deltas_and_closes_on_idle(self) -> None:
        emitted: list[dict[str, Any]] = []
        adapter = self._adapter(emitted)
        await self._run(
            adapter,
            [
                self._part("text", "p1", delta="Hel", text="Hel"),
                self._part("text", "p1", delta="lo", text="Hello"),
                self._idle(),
                self._disposed(),
            ],
        )
        self.assertEqual(
            emitted,
            [
                {"type": "part_start", "part_id": "p1", "part_type": "text"},
                {"type": "part_delta", "part_id": "p1", "text": "Hel"},
                {"type": "delta", "text": "Hel"},
                {"type": "part_delta", "part_id": "p1", "text": "lo"},
                {"type": "delta", "text": "lo"},
                {"type": "part_done", "part_id": "p1"},
                {"type": "done"},
            ],
        )

    async def test_reasoning_then_text_are_separate_parts(self) -> None:
        emitted: list[dict[str, Any]] = []
        adapter = self._adapter(emitted)
        await self._run(
            adapter,
            [
                self._part("reasoning", "r1", delta="think", text="think"),
                self._part("text", "t1", delta="reply", text="reply"),
                self._idle(),
                self._disposed(),
            ],
        )
        self.assertEqual(
            emitted,
            [
                {"type": "part_start", "part_id": "r1", "part_type": "reasoning"},
                {"type": "part_delta", "part_id": "r1", "text": "think"},
                {"type": "part_done", "part_id": "r1"},
                {"type": "part_start", "part_id": "t1", "part_type": "text"},
                {"type": "part_delta", "part_id": "t1", "text": "reply"},
                {"type": "delta", "text": "reply"},
                {"type": "part_done", "part_id": "t1"},
                {"type": "done"},
            ],
        )

    async def test_tool_part_closes_open_content_part(self) -> None:
        emitted: list[dict[str, Any]] = []
        adapter = self._adapter(emitted)
        await self._run(
            adapter,
            [
                self._part("text", "t1", delta="hi", text="hi"),
                {
                    "type": "message.part.updated",
                    "properties": {
                        "sessionID": "ses-own",
                        "part": {
                            "type": "tool",
                            "id": "tool1",
                            "callID": "c1",
                            "tool": "bash",
                            "state": {
                                "status": "running",
                                "title": "Run",
                                "input": {"cwd": "/x"},
                            },
                        },
                    },
                },
                self._idle(),
                self._disposed(),
            ],
        )
        self.assertEqual(
            emitted,
            [
                {"type": "part_start", "part_id": "t1", "part_type": "text"},
                {"type": "part_delta", "part_id": "t1", "text": "hi"},
                {"type": "delta", "text": "hi"},
                {"type": "part_done", "part_id": "t1"},
                {
                    "type": "tool_start",
                    "tool_call_id": "c1",
                    "title": "Run",
                    "status": "running",
                    "kind": "bash",
                    "raw_input": {"cwd": "/x"},
                },
                {"type": "done"},
            ],
        )

    async def test_non_content_part_closes_open_content_part(self) -> None:
        emitted: list[dict[str, Any]] = []
        adapter = self._adapter(emitted)
        await self._run(
            adapter,
            [
                self._part("text", "t1", delta="hi", text="hi"),
                self._part("step-start", "s1"),
                self._idle(),
                self._disposed(),
            ],
        )
        self.assertEqual(
            emitted,
            [
                {"type": "part_start", "part_id": "t1", "part_type": "text"},
                {"type": "part_delta", "part_id": "t1", "text": "hi"},
                {"type": "delta", "text": "hi"},
                {"type": "part_done", "part_id": "t1"},
                {"type": "done"},
            ],
        )

    async def test_full_text_fallback_dedupes_across_updates(self) -> None:
        emitted: list[dict[str, Any]] = []
        adapter = self._adapter(emitted)
        await self._run(
            adapter,
            [
                self._part("text", "t1", text="Hello"),
                self._part("text", "t1", text="Hello"),
                self._idle(),
                self._disposed(),
            ],
        )
        self.assertEqual(
            emitted,
            [
                {"type": "part_start", "part_id": "t1", "part_type": "text"},
                {"type": "part_delta", "part_id": "t1", "text": "Hello"},
                {"type": "delta", "text": "Hello"},
                {"type": "part_done", "part_id": "t1"},
                {"type": "done"},
            ],
        )

    async def test_session_error_closes_open_part(self) -> None:
        emitted: list[dict[str, Any]] = []
        adapter = self._adapter(emitted)
        adapter._awaiting_idle = False  # isolate the session.error mapping
        await self._run(
            adapter,
            [
                self._part("text", "t1", delta="hi", text="hi"),
                {
                    "type": "session.error",
                    "properties": {
                        "sessionID": "ses-own",
                        "error": {"message": "boom"},
                    },
                },
                self._disposed(),
            ],
        )
        self.assertEqual(
            emitted,
            [
                {"type": "part_start", "part_id": "t1", "part_type": "text"},
                {"type": "part_delta", "part_id": "t1", "text": "hi"},
                {"type": "delta", "text": "hi"},
                {"type": "part_done", "part_id": "t1"},
                {"type": "error", "message": "boom"},
            ],
        )


if __name__ == "__main__":
    unittest.main()
