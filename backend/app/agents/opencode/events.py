"""WHATWG-compliant server-sent-event parser.

Implements the field-parsing algorithm from the WHATWG HTML specification
(https://html.spec.whatwg.org/multipage/server-sent-events.html):

- Line endings (CRLF / LF / CR) are normalized by the transport before lines
  reach this parser.
- Comment lines (first character U+003A COLON) are ignored.
- Field names split at the first colon; exactly one leading space on the
  value is removed.
- ``event``, ``id`` and ``retry`` fields are recognized; unknown fields are
  ignored.
- Multiple ``data`` lines are joined with LF on dispatch.
- Dispatch happens only on blank lines, and only when the data buffer is
  non-empty; an incomplete event at EOF is discarded.

Malformed JSON inside ``data`` is deliberately not a parser concern: the raw
string is delivered on :class:`SseMessage` and the consumer decides how to
surface it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass


@dataclass(frozen=True)
class SseMessage:
    """One dispatched SSE event after WHATWG field processing."""

    event: str
    data: str
    id: str | None


def _split_field(line: str) -> tuple[str, str]:
    if ":" not in line:
        return line, ""
    field, _, value = line.partition(":")
    if value.startswith(" "):
        value = value[1:]  # remove exactly one leading space
    return field, value


async def parse_sse_events(lines: AsyncIterator[str]) -> AsyncIterator[SseMessage]:
    """Yield dispatched events from an async stream of SSE text lines."""
    event_name = ""
    data_chunks: list[str] = []
    last_id: str | None = None

    async for raw_line in lines:
        line = raw_line.removesuffix("\r")

        # Blank line: dispatch the current event (only when it has data).
        if line == "":
            if data_chunks:
                yield SseMessage(
                    event=event_name,
                    data="\n".join(data_chunks),
                    id=last_id,
                )
            event_name = ""
            data_chunks = []
            continue

        # Comment line: ignore entirely.
        if line.startswith(":"):
            continue

        field, value = _split_field(line)

        if field == "event":
            event_name = value
        elif field == "data":
            data_chunks.append(value)
        elif field == "id":
            if "\0" not in value:
                last_id = value
        elif field == "retry":
            # Recognized per spec; RTAI never auto-reconnects, so the value
            # is validated but otherwise unused.
            _ = int(value) if value.isdigit() else None
        else:
            continue  # unknown fields ignored per spec

    # End of stream: any buffered event without its terminating blank line is
    # discarded per the WHATWG rules - nothing is emitted here.
