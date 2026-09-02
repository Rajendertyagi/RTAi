"""Health and liveness probe for the RTAI backend.

The AssistantTransport HTTP API lives under ``/assistant``; this module
exposes only the lightweight health endpoint used by deployment probes.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
