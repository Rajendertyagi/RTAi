"""Reasoning-stream projection regression tests (P0 correction).

Locks the wire contract between the backend projector and the PINNED strict
browser accumulator (assistant-stream@0.3.40 ``GorpStreamAccumulator``):

- only ``set`` (existing or append array index) and ``append-text`` (existing
  string target) operations may be emitted;
- a typed reasoning part must exist in browser state BEFORE its first delta;
- the reasoning part keeps its ``type`` field and intended ordering;
- text-only streaming is unchanged;
- a genuine projection write failure records ONE safe diagnostic (fixed
  tokens) instead of silently degrading.

The tests drive the real ``create_run``/``RunController`` and the real
projector helpers, encode chunks with the real ``DataStreamEncoder``, and
apply the resulting ``aui-state`` operations with a faithful strict mirror of
the browser applier.
"""

from __future__ import annotations

import asyncio
import json
import unittest

from assistant_stream import create_run
from assistant_stream.serialization.data_stream import DataStreamEncoder

from app.transport.assistant.acp_state_projector import (
    _append_text_to_assistant,
    _ensure_assistant_message,
    _set_status,
)


class _StrictBrowserApplier:
    """Faithful strict mirror of the pinned browser GorpStreamAccumulator.

    Any operation the pinned client would reject is recorded in ``failures``
    (op type + safe path shape + fixed error class) instead of raising, so one
    run can assert "zero rejections" while still applying later batches.
    """

    def __init__(self, initial: object = None) -> None:
        self.state: object = initial
        self.failures: list[dict[str, object]] = []
        self.ops: list[dict[str, object]] = []

    def apply_batch(self, ops: list[dict[str, object]]) -> None:
        for op in ops:
            op_type = str(op.get("type"))
            path = [str(p) for p in op.get("path", [])]
            self.ops.append({"type": op_type, "path": path})
            try:
                self.state = self._update(self.state, path, op)
            except Exception as exc:  # noqa: BLE001 - mirror records, never raises
                self.failures.append(
                    {
                        "type": op_type,
                        "path": ".".join(path),
                        "error": type(exc).__name__,
                    }
                )

    def _update(self, state: object, path: list[str], op: dict[str, object]) -> object:
        if not path:
            if op["type"] == "set":
                return op["value"]
            if op["type"] == "append-text":
                if not isinstance(state, str):
                    raise TypeError("expected string")
                return state + str(op["value"])
            raise TypeError("invalid operation type")

        if state is None:
            state = {}
        if isinstance(state, list):
            key = path[0]
            idx = int(key)
            if str(idx) != key:
                raise ValueError("non-integer array index")
            if idx < 0 or idx > len(state):
                raise IndexError("array index out of bounds")
            nxt = list(state)
            if idx == len(nxt):
                # JS arrays extend on `nextState[idx] = ...` at idx == length;
                # the pinned client relies on that, so the mirror appends here.
                nxt.append(self._update(None, path[1:], op))
            else:
                nxt[idx] = self._update(nxt[idx], path[1:], op)
            return nxt
        if isinstance(state, dict):
            key = path[0]
            nxt = dict(state)
            nxt[key] = self._update(nxt.get(key), path[1:], op)
            return nxt
        raise TypeError("invalid path container")

    # -- convenience assertions ------------------------------------------
    def last_message_parts(self) -> list[dict[str, object]]:
        messages = self.state["messages"] if isinstance(self.state, dict) else []
        assert isinstance(messages, list) and messages
        last = messages[-1]
        assert isinstance(last, dict)
        parts = last.get("parts")
        assert isinstance(parts, list)
        return [p for p in parts if isinstance(p, dict)]


def _collect_ops(coroutine_body) -> tuple[_StrictBrowserApplier, list[list[dict]]]:
    """Run a projection body against a real RunController and return the
    strict applier (seeded like the browser) plus the ordered op batches.

    The applier is seeded exactly like the pinned browser accumulator: with the
    client-sent state, which always carries ``messages: []`` (the runtime's
    initialState) before any op arrives.
    """

    async def _runner() -> tuple[_StrictBrowserApplier, list[list[dict]]]:
        encoder = DataStreamEncoder()
        batches: list[list[dict]] = []
        applier = _StrictBrowserApplier({"messages": [], "status": "ready"})

        async def run(controller) -> None:
            await coroutine_body(controller)

        async for chunk in create_run(run, state={"messages": [], "status": "ready"}):
            line = encoder.encode_chunk(chunk)
            if not line:
                continue
            code, _, payload = line.partition(":")
            if code == "aui-state":
                ops = json.loads(payload)
                batches.append(ops)
                applier.apply_batch(ops)
        return applier, batches

    return asyncio.run(_runner())


class ReasoningProjectionWireTests(unittest.TestCase):
    def test_reasoning_then_text_streams_valid_ops_in_order(self) -> None:
        """Reasoning-first turn: typed part + valid deltas, then answer text."""

        async def body(controller) -> None:
            _ensure_assistant_message(controller)
            for delta in ("thin", "king"):
                _append_text_to_assistant(controller, delta, kind="reasoning")
            for delta in ("The ", "answer"):
                _append_text_to_assistant(controller, delta, kind="text")
            _set_status(controller, "complete")
            controller.flush()

        applier, _batches = _collect_ops(body)

        self.assertEqual(applier.failures, [])
        parts = applier.last_message_parts()
        self.assertEqual(
            [p.get("type") for p in parts], ["reasoning", "text"],
            "reasoning must precede text in intended part order",
        )
        self.assertEqual(parts[0].get("text"), "thinking")
        self.assertEqual(parts[1].get("text"), "The answer")

    def test_no_append_text_before_its_target_part_exists(self) -> None:
        """Every reasoning append-text must be preceded by the creating set."""

        async def body(controller) -> None:
            _ensure_assistant_message(controller)
            for delta in ("a", "b", "c"):
                _append_text_to_assistant(controller, delta, kind="reasoning")
            controller.flush()

        applier, _batches = _collect_ops(body)
        self.assertEqual(applier.failures, [])

        # Locate the first append-text into the reasoning part's text and the
        # set that created the parts array containing it; the set must come
        # first in flattened stream order.
        first_append = next(
            (
                i
                for i, op in enumerate(applier.ops)
                if op["type"] == "append-text"
                and len(op["path"]) == 5
                and op["path"][2] == "parts"
            ),
            None,
        )
        self.assertIsNotNone(first_append, "reasoning deltas must be streamed")
        creating_set = next(
            (
                i
                for i, op in enumerate(applier.ops[: first_append])
                if op["type"] == "set"
                and len(op["path"]) == 3
                and op["path"][2] == "parts"
            ),
            None,
        )
        self.assertIsNotNone(
            creating_set,
            "the typed reasoning part must be created via set before deltas",
        )

    def test_text_only_streaming_is_unchanged(self) -> None:
        """Text-only turns must not rebuild the parts array."""

        async def body(controller) -> None:
            _ensure_assistant_message(controller)
            for delta in ("Hello", " world"):
                _append_text_to_assistant(controller, delta, kind="text")
            _set_status(controller, "complete")
            controller.flush()

        applier, _batches = _collect_ops(body)

        self.assertEqual(applier.failures, [])
        parts = applier.last_message_parts()
        self.assertEqual(len(parts), 1)
        self.assertEqual(parts[0].get("type"), "text")
        self.assertEqual(parts[0].get("text"), "Hello world")
        parts_array_sets = [
            op
            for op in applier.ops
            if op["type"] == "set" and len(op["path"]) == 3 and op["path"][2] == "parts"
        ]
        self.assertEqual(parts_array_sets, [], "text path must not rebuild parts")

    def test_reasoning_after_text_preserves_content_and_order(self) -> None:
        """Reasoning arriving mid-turn must not corrupt existing text."""

        async def body(controller) -> None:
            _ensure_assistant_message(controller)
            _append_text_to_assistant(controller, "before ", kind="text")
            _append_text_to_assistant(controller, "meta ", kind="reasoning")
            _append_text_to_assistant(controller, "after", kind="text")
            _set_status(controller, "complete")
            controller.flush()

        applier, _batches = _collect_ops(body)

        self.assertEqual(applier.failures, [])
        parts = applier.last_message_parts()
        self.assertEqual([p.get("type") for p in parts], ["reasoning", "text"])
        self.assertEqual(parts[0].get("text"), "meta ")
        self.assertEqual(parts[1].get("text"), "before after")


class _RecordingRecorder:
    """Minimal recorder double matching SessionDiagnosticsRecorder.record."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict]] = []

    def record(self, event: str, level: str = "info", **fields: object) -> None:
        self.events.append((event, level, dict(fields)))


class ProjectionFailureDiagnosticTests(unittest.TestCase):
    def test_genuine_write_failure_records_one_safe_diagnostic(self) -> None:
        recorder = _RecordingRecorder()

        async def body(controller) -> None:
            controller.append_state_text = self._raise  # type: ignore[method-assign]
            _ensure_assistant_message(controller)
            _append_text_to_assistant(
                controller, "delta", kind="reasoning", recorder=recorder
            )
            controller.flush()

        _collect_ops(body)  # must not raise out of the projection path

        self.assertEqual(len(recorder.events), 1, "exactly one safe diagnostic")
        event, level, fields = recorder.events[0]
        self.assertEqual(event, "state.projection.failed")
        self.assertEqual(level, "error")
        self.assertEqual(
            fields, {"reason": "state_write_failed", "handled": True},
            "only fixed tokens may be recorded",
        )

    def test_recorder_none_is_tolerated_on_failure(self) -> None:
        async def body(controller) -> None:
            controller.append_state_text = self._raise  # type: ignore[method-assign]
            _ensure_assistant_message(controller)
            _append_text_to_assistant(controller, "delta", kind="reasoning")
            controller.flush()

        _collect_ops(body)  # must not raise

    @staticmethod
    def _raise(*args: object, **kwargs: object) -> None:
        raise RuntimeError("simulated write failure")


if __name__ == "__main__":
    unittest.main()
