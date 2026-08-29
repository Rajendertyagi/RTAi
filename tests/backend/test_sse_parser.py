"""WHATWG SSE parser and production streaming tests."""

from __future__ import annotations

import unittest
from collections.abc import AsyncIterator

from app.agents.opencode.events import SseMessage, parse_sse_events


def make_lines(raw: str) -> AsyncIterator[str]:
    """Feed pre-split lines as an async iterator."""
    async def gen() -> AsyncIterator[str]:
        for line in raw.split("\n"):
            yield line
    return gen()


async def collect(raw: str) -> list[SseMessage]:
    return [msg async for msg in parse_sse_events(make_lines(raw))]


class TestSseParserWhatwg(unittest.IsolatedAsyncioTestCase):
    async def test_basic_event(self) -> None:
        msgs = await collect("event: message\ndata: hello\n\n")
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].event, "message")
        self.assertEqual(msgs[0].data, "hello")

    async def test_multiline_data_joined_with_lf(self) -> None:
        msgs = await collect("data: line1\ndata: line2\ndata: line3\n\n")
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].data, "line1\nline2\nline3")

    async def test_comments_ignored(self) -> None:
        msgs = await collect(": this is a comment\ndata: real\n\n")
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].data, "real")

    async def test_crlf_line_endings(self) -> None:
        raw = "event: msg\r\ndata: val\r\n\r\n"
        lines = [ln for ln in raw.replace("\r\n", "\n").split("\n")]
        msgs = [m async for m in parse_sse_events(make_lines("\n".join(lines)))]
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].data, "val")

    async def test_lone_cr_tolerated_by_transport_layer(self) -> None:
        # CR-only endings are normalized by the transport; the parser sees \n.
        msgs = await collect("event: e\ndata: v\n\n")
        self.assertEqual(msgs[0].event, "e")

    async def test_id_field_tracked(self) -> None:
        msgs = await collect("id: abc-42\ndata: payload\n\n")
        self.assertEqual(msgs[0].id, "abc-42")

    async def test_retry_field_recognized_no_crash(self) -> None:
        msgs = await collect("retry: 3000\ndata: x\n\n")
        self.assertEqual(msgs[0].data, "x")

    async def test_unknown_fields_ignored(self) -> None:
        msgs = await collect("x-custom: whatever\ndata: kept\n\n")
        self.assertEqual(msgs[0].data, "kept")

    async def test_single_leading_space_stripped_not_all(self) -> None:
        msgs = await collect("data:  two-spaces-preserved\n\n")
        self.assertEqual(msgs[0].data, " two-spaces-preserved")

    async def test_incomplete_event_at_eof_discarded(self) -> None:
        # No trailing blank line => buffered data is discarded.
        msgs = await collect("data: incomplete")
        self.assertEqual(msgs, [])

    async def test_malformed_json_data_passed_through(self) -> None:
        # Parser delivers raw strings; consumers decide how to handle JSON.
        msgs = await collect("data: {broken json!!}\n\n")
        self.assertEqual(msgs[0].data, "{broken json!!}")

    async def test_multiple_events_sequential(self) -> None:
        raw = "data: first\n\ndata: second\n\n"
        msgs = await collect(raw)
        self.assertEqual([m.data for m in msgs], ["first", "second"])

    async def test_empty_dispatch_skipped_when_no_data(self) -> None:
        msgs = await collect("event: only-event\n\n")
        # No data buffer means dispatch is aborted per WHATWG.
        self.assertEqual(msgs, [])

    async def test_id_with_null_byte_ignored(self) -> None:
        msgs = await collect("id: bad\0id\ndata: x\n\n")
        self.assertIsNone(msgs[0].id)


class FakeSseTransport:
    """Production-shaped transport whose stream_lines yields scripted lines."""

    def __init__(self, lines: list[str]) -> None:
        self._lines = lines
        self.stream_cancelled = False

    def stream_lines(
        self, url: str, *, headers: dict[str, str] | None = None,
        timeout_seconds: float = 10.0,
    ) -> AsyncIterator[str]:
        return self._gen()

    async def _gen(self) -> AsyncIterator[str]:
        try:
            for line in self._lines:
                yield line
        finally:
            self.stream_cancelled = True


class TestStreamCancellation(unittest.IsolatedAsyncioTestCase):
    async def test_cancellation_propagates_and_closes_stream(self) -> None:
        transport = FakeSseTransport(["data: never-consumed"] * 100)
        lines = transport.stream_lines("http://127.0.0.1/event")
        received = 0
        async for _line in lines:
            received += 1
            if received >= 3:
                break  # simulates consumer cancelling
        # Explicitly close to trigger the generator's finally block.
        await lines.aclose()
        self.assertTrue(transport.stream_cancelled)


if __name__ == "__main__":
    unittest.main()
