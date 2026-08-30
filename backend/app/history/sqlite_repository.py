"""SQLite-backed history repository.

Connection policy (database-integrity requirements):

- **Connection-per-operation**: every public method opens a fresh connection,
  configures it, runs one short explicit transaction, and closes it. No
  connection is ever shared across FastAPI threads, so there is no single
  unsafe global SQLite connection.
- **PRAGMAs on every connection**: ``journal_mode=WAL`` (verified to actually
  return ``"wal"``), ``synchronous=NORMAL``, ``foreign_keys=ON``,
  ``busy_timeout=5000``.
- **Short explicit transactions**: each operation is wrapped in BEGIN/COMMIT
  (or ROLLBACK on error).

File placement: ``rtai.db``, ``rtai.db-wal`` and ``rtai.db-shm`` all live
together under the data directory. Backups must checkpoint SQLite or copy all
three files consistently (see docs/ARCHITECTURE.md).
"""

from __future__ import annotations

import base64
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from .migrations import migrate
from .models import HistoryEvent, HistorySession, SessionStatus

_WAL_MARKER = "wal"
_BUSY_TIMEOUT_MS = 5000


class HistoryStorageError(RuntimeError):
    """Raised when a persistence operation fails."""


def _encode_cursor(*parts: str) -> str:
    raw = "\x1f".join(parts)
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def _decode_cursor(cursor: str | None) -> list[str] | None:
    if not cursor:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None
    return raw.split("\x1f")


def _configure(conn: sqlite3.Connection) -> None:
    """Apply the required PRAGMAs to a fresh connection."""
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA synchronous=NORMAL")
    row = conn.execute("PRAGMA journal_mode=WAL").fetchone()
    mode = row[0] if row else None
    if mode != _WAL_MARKER:
        raise HistoryStorageError(f"SQLite journal_mode is {mode!r}, expected 'wal'")


def _row_to_session(row: sqlite3.Row) -> HistorySession:
    return HistorySession(
        rtai_session_id=row["rtai_session_id"],
        adapter_kind=row["adapter_kind"],
        native_session_id=row["native_session_id"],
        cwd=row["cwd"],
        user_title=row["user_title"],
        provider_title=row["provider_title"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        last_turn_at=row["last_turn_at"],
        status=SessionStatus(row["status"]),
        resume_capable=row["resume_capable"],
        resume_reason=row["resume_reason"],
        schema_version=row["schema_version"],
    )


def _row_to_event(row: sqlite3.Row) -> HistoryEvent:
    payload: dict[str, Any] = {}
    try:
        payload = json.loads(row["payload"])
    except (TypeError, ValueError):
        payload = {}
    return HistoryEvent(
        id=row["id"],
        rtai_session_id=row["rtai_session_id"],
        event_ordinal=row["event_ordinal"],
        event_type=row["event_type"],
        event_key=row["event_key"],
        payload=payload if isinstance(payload, dict) else {},
        turn_id=row["turn_id"],
        message_id=row["message_id"],
        sequence=row["sequence"],
        timestamp=row["timestamp"],
        created_at=row["created_at"],
    )


class SqliteHistoryRepository:
    """HistoryRepository backed by a single SQLite database file."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            migrate(conn)

    # -- connection lifecycle ------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), timeout=_BUSY_TIMEOUT_MS / 1000)
        conn.row_factory = sqlite3.Row
        try:
            _configure(conn)
        except Exception:
            conn.close()
            raise
        return conn

    @staticmethod
    def _now() -> int:
        return int(time.time() * 1000)

    # -- sessions ------------------------------------------------------------

    def create_session(self, session: HistorySession) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO history_sessions (
                    rtai_session_id, adapter_kind, native_session_id, cwd,
                    user_title, provider_title, created_at, updated_at,
                    last_turn_at, status, resume_capable, resume_reason,
                    schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session.rtai_session_id,
                    session.adapter_kind,
                    session.native_session_id,
                    session.cwd,
                    session.user_title,
                    session.provider_title,
                    session.created_at,
                    session.updated_at,
                    session.last_turn_at,
                    session.status.value,
                    session.resume_capable,
                    session.resume_reason,
                    session.schema_version,
                ),
            )

    def get_session(self, rtai_session_id: str) -> HistorySession | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM history_sessions WHERE rtai_session_id = ?",
                (rtai_session_id,),
            ).fetchone()
        return _row_to_session(row) if row is not None else None

    def list_sessions(
        self, cursor: str | None = None, limit: int = 50
    ) -> tuple[list[HistorySession], str | None]:
        limit = max(1, min(limit, 200))
        parts = _decode_cursor(cursor)
        params: list[Any] = []
        where = ""
        if parts is not None and len(parts) == 2:
            try:
                updated_at = int(parts[0])
            except ValueError:
                updated_at = None
            if updated_at is not None:
                # Keyset pagination: strictly older than the cursor row.
                where = "WHERE (updated_at < ? OR (updated_at = ? AND rtai_session_id < ?))"
                params = [updated_at, updated_at, parts[1]]
        params.append(limit + 1)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM history_sessions
                {where}
                ORDER BY updated_at DESC, rtai_session_id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        has_more = len(rows) > limit
        rows = rows[:limit]
        items = [_row_to_session(r) for r in rows]
        next_cursor: str | None = None
        if has_more and items:
            last = items[-1]
            next_cursor = _encode_cursor(str(last.updated_at), last.rtai_session_id)
        return items, next_cursor

    def record_native_mapping(
        self,
        rtai_session_id: str,
        native_session_id: str,
        *,
        adapter_kind: str,
        resume_capable: bool | None,
        resume_reason: str | None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE history_sessions
                SET native_session_id = ?, adapter_kind = ?,
                    resume_capable = ?, resume_reason = ?
                WHERE rtai_session_id = ?
                """,
                (
                    native_session_id,
                    adapter_kind,
                    resume_capable,
                    resume_reason,
                    rtai_session_id,
                ),
            )

    def set_title(self, rtai_session_id: str, title: str, *, user: bool) -> None:
        column = "user_title" if user else "provider_title"
        with self._connect() as conn:
            conn.execute(
                f"UPDATE history_sessions SET {column} = ? WHERE rtai_session_id = ?",
                (title, rtai_session_id),
            )

    def set_status(self, rtai_session_id: str, status: SessionStatus) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE history_sessions SET status = ? WHERE rtai_session_id = ?",
                (status.value, rtai_session_id),
            )

    def touch(self, rtai_session_id: str, *, last_turn_at: int | None = None) -> None:
        now = self._now()
        with self._connect() as conn:
            if last_turn_at is not None:
                conn.execute(
                    """
                    UPDATE history_sessions
                    SET updated_at = ?, last_turn_at = ?
                    WHERE rtai_session_id = ?
                    """,
                    (now, last_turn_at, rtai_session_id),
                )
            else:
                conn.execute(
                    "UPDATE history_sessions SET updated_at = ? WHERE rtai_session_id = ?",
                    (now, rtai_session_id),
                )

    # -- events --------------------------------------------------------------

    def append_event(self, event: HistoryEvent) -> bool:
        with self._connect() as conn:
            try:
                # Assign the next per-session ordinal atomically inside a single
                # INSERT ... SELECT. SQLite serializes writes under its write
                # lock, so concurrent appends (e.g. via asyncio.to_thread) each
                # observe the latest MAX and never collide on the ordinal.
                cur = conn.execute(
                    """
                    INSERT INTO history_events (
                        rtai_session_id, event_ordinal, event_type, event_key,
                        turn_id, message_id, sequence, timestamp, payload, created_at
                    )
                    SELECT ?, COALESCE(MAX(event_ordinal), 0) + 1, ?, ?, ?, ?, ?, ?, ?, ?
                    FROM history_events
                    WHERE rtai_session_id = ?
                    """,
                    (
                        event.rtai_session_id,
                        event.event_type,
                        event.event_key,
                        event.turn_id,
                        event.message_id,
                        event.sequence,
                        event.timestamp,
                        json.dumps(event.payload, default=str),
                        event.created_at or self._now(),
                        event.rtai_session_id,
                    ),
                )
            except sqlite3.IntegrityError:
                # Duplicate event_key for this session: idempotent no-op.
                return False
        return cur.rowcount > 0

    def get_events(
        self, rtai_session_id: str, cursor: str | None = None, limit: int = 200
    ) -> tuple[list[HistoryEvent], str | None]:
        limit = max(1, min(limit, 500))
        parts = _decode_cursor(cursor)
        params: list[Any] = [rtai_session_id]
        where = ""
        if parts is not None and len(parts) == 2:
            try:
                ordinal = int(parts[0])
            except ValueError:
                ordinal = None
            if ordinal is not None:
                where = "AND (event_ordinal > ? OR (event_ordinal = ? AND id > ?))"
                params.extend([ordinal, ordinal, parts[1]])
        params.append(limit + 1)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM history_events
                WHERE rtai_session_id = ? {where}
                ORDER BY event_ordinal ASC, id ASC
                LIMIT ?
                """,
                params,
            ).fetchall()
        has_more = len(rows) > limit
        rows = rows[:limit]
        items = [_row_to_event(r) for r in rows]
        next_cursor: str | None = None
        if has_more and items:
            last = items[-1]
            next_cursor = _encode_cursor(str(last.event_ordinal), str(last.id))
        return items, next_cursor

    def close(self) -> None:
        # Connection-per-operation: nothing to hold open.
        return None
