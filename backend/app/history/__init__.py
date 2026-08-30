"""Persistent chat history (Phase 5).

Backend-only storage of normalized Protocol v1 conversation events plus the
session metadata needed to list and (in a later phase) resume them. The
repository boundary is provider-neutral: application code depends on
:class:`HistoryRepository`, never on SQLite directly.
"""

from __future__ import annotations

from .models import HistoryEvent, HistorySession, SessionStatus
from .repository import HistoryRepository
from .sqlite_repository import SqliteHistoryRepository

__all__ = [
    "HistoryEvent",
    "HistoryRepository",
    "HistorySession",
    "SessionStatus",
    "SqliteHistoryRepository",
]
