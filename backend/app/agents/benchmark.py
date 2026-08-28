"""Provider-neutral benchmark instrumentation (Phase 2A-B).

Records wall-clock milestones for the later controlled comparison between the
OpenCode Server and ACP adapters. Design guarantees:

- Monotonic clock, injectable for deterministic tests.
- Milestones are a fixed vocabulary; free-form text is never accepted, so
  prompt contents, credentials, environment values or file paths can never
  leak into a record.
- Recording never blocks or affects streaming behavior beyond one dict write.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol


class BenchmarkClock(Protocol):
    def monotonic(self) -> float: ...


class SystemClock:
    """Default clock: time.monotonic()."""

    def monotonic(self) -> float:
        import time

        return time.monotonic()


MILESTONES = (
    "startup",
    "ready",
    "session_created",
    "prompt_accepted",
    "first_event",
    "first_token",
    "completed",
    "cancelled",
)


@dataclass
class BenchmarkRecorder:
    adapter: str
    clock: Callable[[], float]
    _milestones: dict[str, float] = field(default_factory=dict)
    _runtime_ids: dict[str, str] = field(default_factory=dict)
    error_category: str | None = None

    def mark(self, milestone: str) -> None:
        """Record a milestone timestamp; unknown names are rejected loudly."""
        if milestone not in MILESTONES:
            raise ValueError(f"unknown benchmark milestone: {milestone!r}")
        # First observation wins: milestones measure earliest occurrence.
        self._milestones.setdefault(milestone, self.clock())

    def set_runtime_id(self, key: str, value: str) -> None:
        """Store a runtime-supplied identifier (model/session/provider ids)."""
        self._runtime_ids[key] = value

    def fail(self, category: str) -> None:
        self.error_category = category

    def relative(self) -> dict[str, float | None]:
        """Milestones as seconds relative to startup (None if never reached)."""
        origin = self._milestones.get("startup")
        result: dict[str, float | None] = {}
        for name in MILESTONES:
            stamp = self._milestones.get(name)
            result[name] = None if stamp is None or origin is None else round(stamp - origin, 6)
        return result

    def to_json_dict(self) -> dict[str, Any]:
        """Structured, JSON-safe view. Contains timings, ids and category only."""
        return {
            "adapter": self.adapter,
            "metrics_seconds": self.relative(),
            "runtime_ids": dict(self._runtime_ids),
            "error_category": self.error_category,
        }

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_json_dict(), indent=indent)
