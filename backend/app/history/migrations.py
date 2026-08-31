"""Schema versioning and migrations for the history database.

The schema version is tracked in a ``history_meta`` table. On open, the
repository runs any pending migrations in order. Version 1 is the initial
schema; future phases add migrations rather than editing version 1 in place.
"""

from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 1

_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS history_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS history_sessions (
    rtai_session_id TEXT PRIMARY KEY,
    adapter_kind TEXT NOT NULL,
    native_session_id TEXT,
    cwd TEXT NOT NULL,
    user_title TEXT,
    provider_title TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    last_turn_at INTEGER,
    status TEXT NOT NULL,
    resume_capable INTEGER,
    resume_reason TEXT,
    schema_version INTEGER NOT NULL
);

-- Native-session uniqueness is a partial index: SQLite treats NULLs as
-- distinct, so a plain UNIQUE(adapter_kind, native_session_id) would allow
-- duplicate rows whenever native_session_id is NULL. The partial index only
-- enforces uniqueness when a native id is actually present.
CREATE UNIQUE INDEX IF NOT EXISTS idx_history_sessions_native
    ON history_sessions(adapter_kind, native_session_id)
    WHERE native_session_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS history_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rtai_session_id TEXT NOT NULL,
    event_ordinal INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    event_key TEXT NOT NULL,
    turn_id TEXT,
    message_id TEXT,
    sequence INTEGER,
    timestamp INTEGER,
    payload TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    FOREIGN KEY (rtai_session_id) REFERENCES history_sessions(rtai_session_id)
);

-- event_ordinal is monotonically increasing per session: a per-session
-- sequence counter that resets to 1 for each new session.
CREATE UNIQUE INDEX IF NOT EXISTS idx_history_events_ordinal
    ON history_events(rtai_session_id, event_ordinal);

-- Idempotency: event_key is deterministic and non-null, so this unique index
-- reliably rejects duplicate inserts (a nullable composite key would not).
CREATE UNIQUE INDEX IF NOT EXISTS idx_history_events_key
    ON history_events(rtai_session_id, event_key);
"""


def _current_version(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute("SELECT value FROM history_meta WHERE key = 'schema_version'").fetchone()
    except sqlite3.OperationalError:
        return 0
    if row is None:
        return 0
    try:
        return int(row[0])
    except (TypeError, ValueError):
        return 0


def migrate(conn: sqlite3.Connection) -> int:
    """Apply pending migrations and return the resulting schema version."""
    version = _current_version(conn)
    if version < 1:
        conn.executescript(_SCHEMA_V1)
        conn.execute(
            "INSERT OR REPLACE INTO history_meta (key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        version = SCHEMA_VERSION
    return version
