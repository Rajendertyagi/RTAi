"""Minimal async HTTP layer for the OpenCode server adapter.

A tiny Protocol plus a stdlib implementation (urllib inside worker threads)
keeps the dependency graph unchanged. Tests inject fake transports instead of
network I/O.

SSE streaming (``stream_lines``) runs the blocking socket read on a dedicated
worker thread and bridges decoded lines to the event loop through an asyncio
queue: cancelling the generator closes the response, which unblocks the
reader; the thread is then joined so nothing is left behind. Failures raise
:class:`StreamError` with a machine-readable kind.

Line splitting follows universal-newlines semantics (CRLF, LF and CR) with
cross-chunk buffering, and UTF-8 decoding is lossy-safe.
"""

from __future__ import annotations

import asyncio
import base64
import json
import threading
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class HttpResult:
    status: int
    body: bytes

    def json(self) -> Any:
        if not self.body:
            return None
        return json.loads(self.body.decode("utf-8"))


class StreamError(RuntimeError):
    """SSE stream failure with a machine-readable kind."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


class HttpTransport(Protocol):
    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        json_body: Any = None,
        timeout_seconds: float = 10.0,
    ) -> HttpResult: ...

    def stream_lines(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        timeout_seconds: float = 10.0,
    ) -> AsyncIterator[str]:
        """Yield decoded text lines from a streaming SSE response."""
        ...


def basic_auth_header(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _split_universal(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return normalized.split("\n")


class StdlibHttpTransport:
    """urllib-based transport executed off the event loop thread."""

    def __init__(self) -> None:
        # Exposed for test-level inspection of the exact reader thread only.
        self._active_reader_thread: threading.Thread | None = None

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        json_body: Any = None,
        timeout_seconds: float = 10.0,
    ) -> HttpResult:
        body_bytes = (
            json.dumps(json_body).encode("utf-8") if json_body is not None else None
        )
        result = await asyncio.to_thread(
            self._request_sync, method, url, headers, body_bytes, timeout_seconds
        )
        return result

    @staticmethod
    def _request_sync(
        method: str,
        url: str,
        headers: Mapping[str, str] | None,
        body_bytes: bytes | None,
        timeout_seconds: float,
    ) -> HttpResult:
        import urllib.error
        import urllib.request

        request = urllib.request.Request(url, data=body_bytes, method=method)
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        if body_bytes is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                return HttpResult(status=response.status, body=response.read())
        except urllib.error.HTTPError as error:
            return HttpResult(status=error.code, body=error.read())

    def stream_lines(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        timeout_seconds: float = 10.0,
    ) -> AsyncIterator[str]:
        return self._stream_lines(url, dict(headers or {}), timeout_seconds)

    async def _stream_lines(
        self, url: str, headers: dict[str, str], timeout_seconds: float
    ) -> AsyncIterator[str]:
        # The reader runs on a worker thread, so every hand-off into the event
        # loop must use call_soon_threadsafe - a bare queue.put_nowait from
        # another thread does not wake a loop blocked in select() and would
        # deadlock the consumer.
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[Any] = asyncio.Queue()
        state: dict[str, Any] = {"response": None}
        # Lets the consumer signal the reader to stop even before the response
        # object exists (e.g. cancellation while urlopen is still connecting).
        #
        # Limitation: abort_event sets a flag checked between read iterations;
        # it cannot interrupt a blocking ``urlopen()`` or ``read()`` already
        # in progress.  Initial connection blocking is bounded only by the
        # caller-supplied network timeout.  ``response.close()`` is called
        # only when a response object exists (guarded by state lookup).
        abort_event = threading.Event()

        def open_and_read() -> None:
            import urllib.error
            import urllib.request

            response: Any = None
            try:
                request = urllib.request.Request(url)
                for key, value in headers.items():
                    request.add_header(key, value)
                request.add_header("Accept", "text/event-stream")
                response = urllib.request.urlopen(request, timeout=timeout_seconds)
                state["response"] = response

                content_type = response.headers.get_content_type()
                if content_type != "text/event-stream":
                    loop.call_soon_threadsafe(
                        queue.put_nowait,
                        StreamError(
                            "bad_content_type",
                            f"event endpoint returned content-type {content_type!r}",
                        ),
                    )
                    return

                pending = ""
                while not abort_event.is_set():
                    chunk = response.read(1024)
                    if not chunk:
                        break
                    decoded = pending + chunk.decode("utf-8", errors="replace")
                    lines = _split_universal(decoded)
                    pending = lines.pop()
                    for line in lines:
                        loop.call_soon_threadsafe(queue.put_nowait, line)
                        if abort_event.is_set():
                            break
                if pending and not abort_event.is_set():
                    loop.call_soon_threadsafe(queue.put_nowait, pending)
                if not abort_event.is_set():
                    loop.call_soon_threadsafe(queue.put_nowait, None)  # EOF marker
            except Exception as exc:
                loop.call_soon_threadsafe(
                    queue.put_nowait, _classify_stream_failure(exc)
                )
            finally:
                if response is not None and hasattr(response, "close"):
                    response.close()

        reader_thread = threading.Thread(
            target=open_and_read, name="rtai-sse-reader", daemon=True
        )
        self._active_reader_thread = reader_thread
        reader_thread.start()

        try:
            while True:
                item = await queue.get()
                if isinstance(item, StreamError):
                    raise item
                if item is None:
                    break
                yield item
        finally:
            # Signal the reader to stop, then release the socket off the event
            # loop (response.close() can block on a lingering connection).
            abort_event.set()
            response = state.get("response")
            if response is not None and hasattr(response, "close"):
                await asyncio.to_thread(response.close)
            # Bounded join: closing the response unblocks the reader quickly.
            await asyncio.to_thread(reader_thread.join, 5.0)
            if reader_thread.is_alive():
                raise StreamError(
                    "shutdown_failed",
                    "SSE reader thread did not terminate after stream close",
                )


def _classify_stream_failure(exc: Exception) -> Exception:
    import urllib.error

    if isinstance(exc, StreamError):
        return exc
    if isinstance(exc, urllib.error.HTTPError):
        kind = "auth_failed" if exc.code in (401, 403) else "connect_failed"
        detail = exc.read()[:200].decode("utf-8", errors="replace")
        return StreamError(kind, f"HTTP {exc.code} on event endpoint: {detail}")
    return StreamError("connect_failed", f"{type(exc).__name__}: {exc}")
