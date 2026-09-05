from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/api/health")
async def health() -> dict[str, str]:
    """Minimal liveness probe: proves app availability, exposes no internals."""
    return {"status": "ok"}


@router.get("/api/diagnostics")
async def diagnostics(request: Request) -> dict[str, Any]:
    """Bounded, safe, system-wide diagnostics snapshot (read-only).

    Works before any chat session/adapter exists and while AssistantTransport
    is unavailable: it reads only the app supervisor (lifecycle status + the
    ONE central diagnostics hub) and the session registry counts. No session
    id lookup, no adapter calls, no transport state, no WebSocket.

    Safe-data rules — the response contains ONLY:
    - app status token: ``starting`` | ``ready`` | ``shutting_down``
    - safe counts: liveSessions / creatingSessions / closingSessions /
      liveAdapters (bounded ints)
    - bounded recent events (max 200) from the central hub, each carrying only
      a timestamp, a stable event name, level, origin, short correlation ids,
      fixed status/kind tokens, booleans, and bounded counts.

    Prompts, text, responses, file paths, tool args/results, ACP payloads,
    process command lines or PIDs, credentials, tokens, headers, and
    model/config identifiers or values are never recorded — the hub's
    sanitizer is the single enforcement point at record time, so nothing
    unsafe can reach this response.
    """
    supervisor = getattr(request.app.state, "supervisor", None)
    if supervisor is None:
        # Supervisor not attached (should not happen): still answer safely and
        # honestly instead of erroring, so the Logs page keeps working.
        return {"app": {"status": "unknown"}, "counts": {}, "events": []}
    return supervisor.snapshot()
