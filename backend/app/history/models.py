"""History domain models.

These are the persisted shapes for one chat session and its ordered event
stream. They are deliberately provider-neutral: ``rtai_session_id`` is a
server-assigned id, while ``native_session_id`` is whatever the underlying
agent adapter called its session (OpenCode ACP session id, server session id,
...). The two are kept separate so the transcript can be listed and replayed
without ever assuming a provider's id scheme.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SessionStatus(str, Enum):
    """Lifecycle state of a persisted session."""

    ACTIVE = "active"
    INACTIVE = "inactive"


@dataclass(frozen=True)
class HistorySession:
    """One persisted chat session."""

    rtai_session_id: str
    adapter_kind: str
    cwd: str
    created_at: int
    updated_at: int
    last_turn_at: int | None = None
    native_session_id: str | None = None
    user_title: str | None = None
    provider_title: str | None = None
    status: SessionStatus = SessionStatus.ACTIVE
    # Resume capability state discovered at runtime (provider-neutral flags).
    resume_capable: bool | None = None
    resume_reason: str | None = None
    schema_version: int = 1


@dataclass(frozen=True)
class HistoryEvent:
    """One persisted normalized Protocol v1 event.

    ``event_ordinal`` is a repository-assigned, monotonically increasing
    counter scoped to the session. It is the authoritative ordering key: the
    wire ``sequence`` may reset per turn or be absent, so it is never used for
    ordering or pagination. ``event_key`` is a deterministic, non-null
    idempotency key unique per session (see the repository schema).
    """

    rtai_session_id: str
    event_type: str
    event_key: str
    payload: dict[str, Any] = field(default_factory=dict)
    turn_id: str | None = None
    message_id: str | None = None
    sequence: int | None = None
    timestamp: int | None = None
    created_at: int = 0
    # Repository-assigned on read; 0 is a placeholder for appends.
    id: int = 0
    event_ordinal: int = 0
