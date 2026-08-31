"""Real StdlibHttpTransport streaming tests against a loopback HTTP server.

These exercise the actual production transport (not FakeSseTransport) using a
stdlib ``ThreadingHTTPServer`` bound to an ephemeral loopback port. No external
services, no OpenCode process, no fixed ports are touched.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import http.server
import threading
import unittest
from collections.abc import AsyncIterator

from app.agents.opencode.http_client import (
    StdlibHttpTransport,
    StreamError,
    basic_auth_header,
)


class _Handler(http.server.BaseHTTPRequestHandler):
    # HTTP/1.0: connection-close delimits the stream; urllib reads until EOF.
    protocol_version = "HTTP/1.0"

    def log_message(self, *args: object) -> None:  # keep test output clean
        pass

    def _record_headers(self) -> None:
        self.server.received_headers = dict(self.headers)  # type: ignore[attr-defined]

    def do_GET(self) -> None:
        self._record_headers()
        scenario = self.server.scenario  # type: ignore[attr-defined]
        kind = scenario.get("kind", "stream")

        if kind == "unauthorized":
            self.send_response(scenario.get("code", 401))
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"unauthorized"}')
            return

        if kind == "bad_content_type":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
            return

        if kind == "delay_then_200":
            # Hold the connection open past the moment the consumer cancels,
            # so the reader thread is still inside urlopen/read at cancel time.
            threading.Event().wait(scenario.get("delay", 0.2))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(scenario.get("body", b""))
            self.wfile.flush()
            return

        # default: stream an SSE body, optionally split into delayed chunks.
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        body = scenario.get("body", b"")
        delay = scenario.get("delay", 0.0)
        chunk_size = scenario.get("chunk_size")
        if chunk_size:
            for i in range(0, len(body), chunk_size):
                self.wfile.write(body[i : i + chunk_size])
                self.wfile.flush()
                if delay:
                    threading.Event().wait(delay)
        else:
            self.wfile.write(body)
            self.wfile.flush()
            if delay:
                threading.Event().wait(delay)


class ProductionTransportTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._servers: list[http.server.ThreadingHTTPServer] = []

    def tearDown(self) -> None:
        for server in self._servers:
            server.shutdown()
            server.server_close()
        self._servers.clear()

    def _start(self, scenario: dict) -> tuple[http.server.ThreadingHTTPServer, int]:
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        server.scenario = scenario  # type: ignore[attr-defined]
        server.received_headers = {}  # type: ignore[attr-defined]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self._servers.append(server)
        return server, int(server.server_address[1])

    async def _collect(self, gen: AsyncIterator[str]) -> list[str]:
        out: list[str] = []
        async for line in gen:
            out.append(line)
        return out

    async def test_successful_stream_yields_lines(self) -> None:
        _, port = self._start(
            {"kind": "stream", "body": b"data: hello\n\ndata: world\n\n"}
        )
        transport = StdlibHttpTransport()
        lines = await self._collect(
            transport.stream_lines(f"http://127.0.0.1:{port}/event")
        )
        self.assertEqual(lines, ["data: hello", "", "data: world", ""])

    async def test_basic_auth_header_sent(self) -> None:
        server, port = self._start({"kind": "stream", "body": b""})
        transport = StdlibHttpTransport()
        auth = basic_auth_header("alice", "secret")
        await self._collect(
            transport.stream_lines(
                f"http://127.0.0.1:{port}/event", headers=auth
            )
        )
        received = server.received_headers  # type: ignore[attr-defined]
        expected = "Basic " + base64.b64encode(b"alice:secret").decode()
        self.assertEqual(received.get("Authorization"), expected)

    async def test_accept_header_sent(self) -> None:
        server, port = self._start({"kind": "stream", "body": b""})
        transport = StdlibHttpTransport()
        await self._collect(
            transport.stream_lines(f"http://127.0.0.1:{port}/event")
        )
        received = server.received_headers  # type: ignore[attr-defined]
        self.assertEqual(received.get("Accept"), "text/event-stream")

    async def test_incremental_lines_arrive_before_stream_finishes(self) -> None:
        # Two events separated by a delay; the consumer must observe the first
        # line without waiting for the second to be produced.
        _, port = self._start(
            {
                "kind": "stream",
                "body": b"data: one\n\ndata: two\n\n",
                "delay": 0.15,
                "chunk_size": 64,
            }
        )
        transport = StdlibHttpTransport()
        gen = transport.stream_lines(f"http://127.0.0.1:{port}/event")
        first = await gen.__anext__()
        self.assertEqual(first, "data: one")
        rest = await self._collect(gen)
        self.assertIn("data: two", rest)

    async def test_lf_crlf_and_cr_chunk_boundaries(self) -> None:
        # Mix line endings and split a logical line across two TCP writes.
        raw = b"data: a\r\ndata: b\npart: c\r\ndata: d"
        _, port = self._start(
            {"kind": "stream", "body": raw, "chunk_size": 7}
        )
        transport = StdlibHttpTransport()
        lines = await self._collect(
            transport.stream_lines(f"http://127.0.0.1:{port}/event")
        )
        # Universal-newline normalization collapses \r\n and \r to \n.
        self.assertIn("data: a", lines)
        self.assertIn("data: b", lines)
        self.assertIn("part: c", lines)
        self.assertIn("data: d", lines)

    async def test_http_401_raises_auth_failed(self) -> None:
        _, port = self._start({"kind": "unauthorized", "code": 401})
        transport = StdlibHttpTransport()
        with self.assertRaises(StreamError) as ctx:
            await self._collect(
                transport.stream_lines(f"http://127.0.0.1:{port}/event")
            )
        self.assertEqual(ctx.exception.kind, "auth_failed")

    async def test_http_403_raises_auth_failed(self) -> None:
        _, port = self._start({"kind": "unauthorized", "code": 403})
        transport = StdlibHttpTransport()
        with self.assertRaises(StreamError) as ctx:
            await self._collect(
                transport.stream_lines(f"http://127.0.0.1:{port}/event")
            )
        self.assertEqual(ctx.exception.kind, "auth_failed")

    async def test_bad_content_type_raises_bad_content_type(self) -> None:
        _, port = self._start({"kind": "bad_content_type"})
        transport = StdlibHttpTransport()
        with self.assertRaises(StreamError) as ctx:
            await self._collect(
                transport.stream_lines(f"http://127.0.0.1:{port}/event")
            )
        self.assertEqual(ctx.exception.kind, "bad_content_type")

    async def test_connection_refused_raises_connect_failed(self) -> None:
        # Start, capture the port, then fully release it so nothing listens.
        server, port = self._start({"kind": "stream", "body": b""})
        server.shutdown()
        server.server_close()
        self._servers.remove(server)
        transport = StdlibHttpTransport()
        with self.assertRaises(StreamError) as ctx:
            await self._collect(
                transport.stream_lines(f"http://127.0.0.1:{port}/event")
            )
        self.assertEqual(ctx.exception.kind, "connect_failed")

    async def test_normal_eof_terminates_cleanly(self) -> None:
        _, port = self._start({"kind": "stream", "body": b""})
        transport = StdlibHttpTransport()
        lines = await self._collect(
            transport.stream_lines(f"http://127.0.0.1:{port}/event")
        )
        self.assertEqual(lines, [])

    async def test_malformed_utf8_is_decoded_safely(self) -> None:
        # Invalid UTF-8 bytes must not crash the reader (errors="replace").
        _, port = self._start({"kind": "stream", "body": b"data: \xff\xfe\n\n"})
        transport = StdlibHttpTransport()
        lines = await self._collect(
            transport.stream_lines(f"http://127.0.0.1:{port}/event")
        )
        self.assertTrue(any("\ufffd" in line for line in lines))

    async def test_cancellation_closes_response_and_thread(self) -> None:
        _, port = self._start(
            {"kind": "stream", "body": b"data: one\n\ndata: two\n\n", "delay": 0.1}
        )
        transport = StdlibHttpTransport()
        gen = transport.stream_lines(f"http://127.0.0.1:{port}/event")
        received = await gen.__anext__()
        self.assertEqual(received, "data: one")
        await gen.aclose()
        thread = transport._active_reader_thread
        self.assertIsNotNone(thread)
        # Bounded wait for the exact reader thread to exit.
        for _ in range(40):
            if not thread.is_alive():
                break
            await asyncio.sleep(0.05)
        self.assertFalse(thread.is_alive())

    async def test_cancellation_before_response_initialized_terminates_thread(
        self,
    ) -> None:
        # Server holds the connection open; consumer cancels before the reader
        # thread has even built its response object. The owned reader thread must
        # still be torn down (no leaked thread, no leaked socket).
        _, port = self._start({"kind": "delay_then_200", "delay": 0.3})
        transport = StdlibHttpTransport()
        gen = transport.stream_lines(f"http://127.0.0.1:{port}/event")
        # Start the generator body (which spawns the reader thread) without
        # awaiting a value, so the response object is not yet constructed.
        task = asyncio.get_running_loop().create_task(gen.__anext__())
        await asyncio.sleep(0.05)
        thread = transport._active_reader_thread
        self.assertIsNotNone(thread)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        # Bounded wait for the exact reader thread to exit.
        for _ in range(40):
            if not thread.is_alive():
                break
            await asyncio.sleep(0.05)
        self.assertFalse(thread.is_alive())


if __name__ == "__main__":
    unittest.main()
