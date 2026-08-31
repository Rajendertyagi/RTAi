"""Provider-neutral history repository boundary.

Application code (WebSocket handler, REST routes) depends on this Protocol,
never on SQLite directly. This keeps the storage backend swappable and lets
tests inject a fake repository.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .errors import CursorValidationError
from .models import HistoryEvent, HistorySession, SessionStatus

__all__ = ["CursorValidationError", "HistoryRepository"]


@runtime_checkable
class HistoryRepository(Protocol):
    """Persistence contract for chat history.

    All methods are synchronous and short-lived; implementations must not
    hold a connection open across calls (see the SQLite implementation for
    the connection-per-operation policy).
    """

    def create_session(self, session: HistorySession) -> None:
        """Insert a new session. Idempotent on the same rtai_session_id."""
        ...

    def get_session(self, rtai_session_id: str) -> HistorySession | None:
        """Return one session, or None when unknown."""
        ...

    def list_sessions(
        self, cursor: str | None = None, limit: int = 50
    ) -> tuple[list[HistorySession], str | None]:
        """List sessions newest-first with an opaque cursor.

        Returns ``(items, next_cursor)``; ``next_cursor`` is None when there
        are no more pages.
        """
        ...

    def record_native_mapping(
        self,
        rtai_session_id: str,
        native_session_id: str,
        *,
        adapter_kind: str,
        resume_capable: bool | None,
        resume_reason: str | None,
    ) -> None:
        """Attach the provider's native session id and resume capability state."""
        ...

    def set_title(self, rtai_session_id: str, title: str, *, user: bool) -> None:
        """Set the user or provider title for a session."""
        ...

    def set_status(self, rtai_session_id: str, status: SessionStatus) -> None:
        """Update the session lifecycle status."""
        ...

    def touch(self, rtai_session_id: str, *, last_turn_at: int | None = None) -> None:
        """Bump updated_at (and optionally last_turn_at) for a session."""
        ...

    def append_event(self, event: HistoryEvent) -> bool:
        """Persist one event idempotently.

        Returns True when the event was newly inserted, False when it was a
        duplicate (same event_key already present for the session).
        """
        ...

    def get_events(
        self, rtai_session_id: str, cursor: str | None = None, limit: int = 200
    ) -> tuple[list[HistoryEvent], str | None]:
        """Return events in ordinal order with an opaque cursor.

        Returns ``(items, next_cursor)``; ``next_cursor`` is None when there
        are no more pages.
        """
        ...

    def close(self) -> None:
        """Release any resources held by the repository."""
        ...
