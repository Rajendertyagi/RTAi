"""History persistence error types.

These are shared between the repository protocol and the SQLite
implementation so the API layer can catch typed errors without depending on
SQLite internals. ``CursorValidationError`` is a client-input error (mapped to
HTTP 400); ``HistoryStorageError`` is an internal persistence failure.
"""

from __future__ import annotations


class HistoryStorageError(RuntimeError):
    """Raised when a persistence operation fails."""


class CursorValidationError(ValueError):
    """Raised when a non-empty cursor is malformed.

    Distinct from :class:`HistoryStorageError` so the API layer can map it to
    HTTP 400 without conflating a bad client input with an internal failure.
    """


__all__ = ["CursorValidationError", "HistoryStorageError"]
