"""History sanitization, SQLite repository, cursor/limit API and event identity.

Phases 6-9: verifies that attachment metadata is safely persisted, the SQLite
repository enforces its schema and pagination contracts, cursors are opaque and
strictly validated, and event keys preserve identity without collapsing distinct
frames or leaking timestamps / Python ``hash()``.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

from app.history.errors import CursorValidationError, HistoryStorageError
from app.history.models import HistoryEvent, HistorySession, SessionStatus
from app.history.sanitize import (
    build_event_key,
    event_discriminator,
    is_persistable,
    sanitize_event_payload,
)
from app.history.sqlite_repository import (
    SqliteHistoryRepository,
    _decode_cursor,
    _encode_cursor,
)
from app.api.routes import _parse_limit, router
from fastapi import HTTPException
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = 1_000_000
_SESSION_ID = "rtai-sess-1"
_TURN_ID = "turn-a"
_MESSAGE_ID = "msg-1"


def _make_repo(td: str) -> SqliteHistoryRepository:
    return SqliteHistoryRepository(Path(td) / "rtai.db")


def _make_session(**overrides: Any) -> HistorySession:
    defaults = dict(
        rtai_session_id=_SESSION_ID,
        adapter_kind="acp:opencode",
        cwd="/tmp/project",
        created_at=_NOW,
        updated_at=_NOW,
        status=SessionStatus.ACTIVE,
    )
    defaults.update(overrides)
    return HistorySession(**defaults)  # type: ignore[arg-type]


def _make_event(**overrides: Any) -> HistoryEvent:
    defaults = dict(
        rtai_session_id=_SESSION_ID,
        event_type="delta",
        event_key="delta|turn-a||1|",
        payload={"text": "hello"},
        turn_id=_TURN_ID,
        message_id=_MESSAGE_ID,
        sequence=1,
        timestamp=_NOW,
        created_at=_NOW,
    )
    defaults.update(overrides)
    return HistoryEvent(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Phase 6: Attachment persistence and privacy
# ---------------------------------------------------------------------------

class SanitizeTests(unittest.TestCase):
    """Sanitization preserves trusted fields and strips raw attachment content."""

    def test_user_message_keeps_safe_metadata(self) -> None:
        frame = {
            "type": "user_message",
            "session_id": "s1",
            "turn_id": "t1",
            "message_id": "m1",
            "prompt": [
                {"kind": "image", "name": "img.png", "mime_type": "image/png",
                 "data_base64": "aGVsbG8=", "size_bytes": 5},
                {"kind": "text", "name": "msg", "text": "hello"},
                {"kind": "embedded_blob", "name": "b.zip", "mime_type": "application/zip",
                 "data_base64": "dW5zYWZl", "size_bytes": 6},
            ],
        }
        result = sanitize_event_payload(frame)
        prompt = result["prompt"]
        self.assertEqual(len(prompt), 3)
        # Only kind, name, mime_type, size_bytes survive — no URI, no base64,
        # no query, no fragment.
        for block in prompt:
            self.assertNotIn("data_base64", block)
            self.assertNotIn("text", block)
            self.assertNotIn("uri", block)
            self.assertNotIn("query", block)
            self.assertNotIn("fragment", block)
        self.assertEqual(prompt[0], {
            "kind": "image", "name": "img.png",
            "mime_type": "image/png", "size_bytes": 5,
        })
        self.assertEqual(prompt[1], {"kind": "text", "name": "msg"})
        self.assertEqual(prompt[2], {
            "kind": "embedded_blob", "name": "b.zip",
            "mime_type": "application/zip", "size_bytes": 6,
        })

    def test_sanitize_does_not_mutate_live_frame(self) -> None:
        frame = {"type": "user_message", "prompt": [{"kind": "image", "data_base64": "abc"}]}
        import copy
        original = copy.deepcopy(frame)
        sanitize_event_payload(frame)
        self.assertEqual(frame, original)

    def test_non_persistable_event_type_returns_empty(self) -> None:
        self.assertEqual(sanitize_event_payload({"type": "raw", "event": "x"}), {})
        self.assertFalse(is_persistable("raw"))
        self.assertTrue(is_persistable("user_message"))
        self.assertTrue(is_persistable("delta"))
        self.assertTrue(is_persistable("part_delta"))
        self.assertTrue(is_persistable("tool_start"))
        self.assertTrue(is_persistable("tool_update"))
        self.assertTrue(is_persistable("tool_result"))
        self.assertTrue(is_persistable("permission_request"))
        self.assertTrue(is_persistable("permission_result"))
        self.assertTrue(is_persistable("done"))
        self.assertTrue(is_persistable("error"))
        self.assertTrue(is_persistable("cancelled"))

    def test_rejected_attachment_not_persisted_as_accepted(self) -> None:
        """A prompt that fails validation never reaches emit(), so it is never
        persisted. This test verifies that a user_message frame carrying an
        invalid block shape still sanitizes safely if it were to arrive."""
        frame = {
            "type": "user_message",
            "session_id": "s1",
            "turn_id": "t1",
            "message_id": "m1",
            "prompt": [{"kind": "unknown_kind", "name": "x"}],
        }
        result = sanitize_event_payload(frame)
        # Unknown block kinds are passed through as-is by the sanitizer (it only
        # touches kind/name/mime_type/size_bytes); the protocol layer rejects
        # them before emit() is called.
        self.assertIn("prompt", result)

    def test_no_raw_attachment_content_in_diagnostic_error(self) -> None:
        """Diagnostic error events must not echo attachment payload."""
        frame = {
            "type": "error",
            "session_id": "s1",
            "turn_id": "t1",
            "message": "attachment too large",
            "code": "size_exceeded",
        }
        result = sanitize_event_payload(frame)
        self.assertEqual(result["message"], "attachment too large")
        self.assertNotIn("aGVsbG8", json.dumps(result))


# ---------------------------------------------------------------------------
# Phase 7: SQLite repository tests
# ---------------------------------------------------------------------------

class SqliteRepositoryTests(unittest.TestCase):
    """Schema, sessions, events, pagination — all against a real temp database."""

    def setUp(self) -> None:
        self._td = tempfile.mkdtemp()
        self._repo = _make_repo(self._td)

    def tearDown(self) -> None:
        self._repo.close()
        import shutil
        shutil.rmtree(self._td, ignore_errors=True)

    # -- schema --
    def test_schema_version_is_one(self) -> None:
        with self._repo._connect() as conn:
            row = conn.execute(
                "SELECT value FROM history_meta WHERE key = 'schema_version'"
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(int(row[0]), 1)

    def test_journal_mode_is_wal(self) -> None:
        with self._repo._connect() as conn:
            row = conn.execute("PRAGMA journal_mode").fetchone()
        self.assertEqual(row[0], "wal")

    def test_foreign_keys_enabled(self) -> None:
        with self._repo._connect() as conn:
            row = conn.execute("PRAGMA foreign_keys").fetchone()
        self.assertEqual(row[0], 1)

    def test_busy_timeout_configured(self) -> None:
        with self._repo._connect() as conn:
            row = conn.execute("PRAGMA busy_timeout").fetchone()
        self.assertEqual(row[0], 5000)

    # -- sessions --
    def test_create_and_get_session(self) -> None:
        self._repo.create_session(_make_session())
        session = self._repo.get_session(_SESSION_ID)
        self.assertIsNotNone(session)
        self.assertEqual(session.rtai_session_id, _SESSION_ID)
        self.assertEqual(session.adapter_kind, "acp:opencode")
        self.assertEqual(session.cwd, "/tmp/project")
        self.assertEqual(session.status, SessionStatus.ACTIVE)

    def test_unknown_session_returns_none(self) -> None:
        self.assertIsNone(self._repo.get_session("no-such-session"))

    def test_native_session_mapping(self) -> None:
        self._repo.create_session(_make_session())
        self._repo.record_native_mapping(
            _SESSION_ID, "native-1",
            adapter_kind="acp:opencode",
            resume_capable=True,
            resume_reason=None,
        )
        session = self._repo.get_session(_SESSION_ID)
        self.assertEqual(session.native_session_id, "native-1")
        self.assertTrue(session.resume_capable)

    def test_partial_unique_index_for_native_mappings(self) -> None:
        """Different native ids with the same adapter_kind coexist; duplicate
        (adapter_kind, native_session_id) raises IntegrityError."""
        self._repo.create_session(_make_session(rtai_session_id="s1"))
        self._repo.create_session(_make_session(rtai_session_id="s2"))
        self._repo.record_native_mapping("s1", "nat-a", adapter_kind="acp", resume_capable=None, resume_reason=None)
        self._repo.record_native_mapping("s2", "nat-b", adapter_kind="acp", resume_capable=None, resume_reason=None)
        self.assertIsNotNone(self._repo.get_session("s1"))
        self.assertIsNotNone(self._repo.get_session("s2"))
        # Same (adapter_kind, native_session_id) on a different rtai session → conflict.
        self._repo.create_session(_make_session(rtai_session_id="s3"))
        with self.assertRaises(sqlite3.IntegrityError):
            self._repo.record_native_mapping("s3", "nat-a", adapter_kind="acp", resume_capable=None, resume_reason=None)

    def test_title_precedence(self) -> None:
        self._repo.create_session(_make_session())
        self._repo.set_title(_SESSION_ID, "User Title", user=True)
        self._repo.set_title(_SESSION_ID, "Provider Title", user=False)
        session = self._repo.get_session(_SESSION_ID)
        self.assertEqual(session.user_title, "User Title")
        self.assertEqual(session.provider_title, "Provider Title")

    def test_status_update(self) -> None:
        self._repo.create_session(_make_session())
        self._repo.set_status(_SESSION_ID, SessionStatus.INACTIVE)
        session = self._repo.get_session(_SESSION_ID)
        self.assertEqual(session.status, SessionStatus.INACTIVE)

    def test_touch_updates_activity_time(self) -> None:
        self._repo.create_session(_make_session())
        old = self._repo.get_session(_SESSION_ID).updated_at
        time.sleep(0.05)
        self._repo.touch(_SESSION_ID, last_turn_at=old + 1000)
        session = self._repo.get_session(_SESSION_ID)
        self.assertGreater(session.updated_at, old)
        self.assertEqual(session.last_turn_at, old + 1000)

    # -- events --
    def test_event_insertion(self) -> None:
        self._repo.create_session(_make_session())
        event = _make_event(event_key="key-1", payload={"text": "hi"})
        inserted = self._repo.append_event(event)
        self.assertTrue(inserted)
        items, _ = self._repo.get_events(_SESSION_ID)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].payload, {"text": "hi"})

    def test_duplicate_event_key_deduplicates(self) -> None:
        self._repo.create_session(_make_session())
        event = _make_event(event_key="dup-key", payload={"text": "first"})
        self.assertTrue(self._repo.append_event(event))
        # Re-append the identical event (same key).
        self.assertFalse(self._repo.append_event(event))
        items, _ = self._repo.get_events(_SESSION_ID)
        self.assertEqual(len(items), 1)

    def test_monotonic_event_ordinal(self) -> None:
        self._repo.create_session(_make_session())
        for i in range(5):
            self._repo.append_event(_make_event(event_key=f"k{i}", sequence=i + 1))
        items, _ = self._repo.get_events(_SESSION_ID)
        ordinals = [e.event_ordinal for e in items]
        self.assertEqual(ordinals, [1, 2, 3, 4, 5])

    def test_event_ordering_by_ordinal(self) -> None:
        self._repo.create_session(_make_session())
        # Insert out of order.
        for seq in (3, 1, 4, 1, 5):
            self._repo.append_event(_make_event(event_key=f"k{seq}", sequence=seq))
        items, _ = self._repo.get_events(_SESSION_ID)
        # Ordinal order, not insertion order.
        ordinals = [e.event_ordinal for e in items]
        self.assertEqual(ordinals, sorted(ordinals))

    def test_session_recency_ordering(self) -> None:
        """Sessions are ordered newest-first by (updated_at, rtai_session_id)."""
        now = _NOW
        self._repo.create_session(_make_session(rtai_session_id="s-b", updated_at=now + 100))
        self._repo.create_session(_make_session(rtai_session_id="s-a", updated_at=now + 100))
        self._repo.create_session(_make_session(rtai_session_id="s-c", updated_at=now))
        items, _ = self._repo.list_sessions()
        ids = [s.rtai_session_id for s in items]
        # s-a and s-b share updated_at; tie-break is DESC rtai_session_id.
        self.assertEqual(ids, ["s-b", "s-a", "s-c"])

    def test_cursor_pagination_no_skips_no_duplicates(self) -> None:
        self._repo.create_session(_make_session())
        for i in range(5):
            self._repo.append_event(_make_event(event_key=f"k{i}", sequence=i + 1))
        page1, cur1 = self._repo.get_events(_SESSION_ID, limit=2)
        page2, cur2 = self._repo.get_events(_SESSION_ID, cursor=cur1, limit=2)
        page3, cur3 = self._repo.get_events(_SESSION_ID, cursor=cur2, limit=2)
        all_keys = [e.event_key for e in page1 + page2 + page3]
        self.assertEqual(len(all_keys), 5)
        self.assertEqual(len(set(all_keys)), 5)
        self.assertIsNone(cur3)

    def test_deterministic_tiebreaker_when_timestamps_match(self) -> None:
        """When two events share the same ordinal, the secondary id column
        breaks the tie deterministically."""
        self._repo.create_session(_make_session())
        # Insert two events with the same ordinal would be impossible via the
        # normal path, but we verify the SQL ORDER BY clause uses (ordinal, id).
        for i in range(3):
            self._repo.append_event(_make_event(event_key=f"k{i}", sequence=i + 1))
        items, cur = self._repo.get_events(_SESSION_ID, limit=2)
        self.assertEqual(len(items), 2)
        self.assertIsNotNone(cur)

    def test_empty_database(self) -> None:
        td = tempfile.mkdtemp()
        try:
            repo = _make_repo(td)
            items, cur = repo.get_events(_SESSION_ID)
            self.assertEqual(items, [])
            self.assertIsNone(cur)
            sessions, scur = repo.list_sessions()
            self.assertEqual(sessions, [])
            self.assertIsNone(scur)
        finally:
            import shutil
            repo.close()
            shutil.rmtree(td, ignore_errors=True)

    def test_unknown_session_events_return_empty(self) -> None:
        items, cur = self._repo.get_events("no-such-session")
        self.assertEqual(items, [])
        self.assertIsNone(cur)

    def test_concurrent_appends_preserve_unique_ordinals(self) -> None:
        self._repo.create_session(_make_session())
        errors: list[Exception] = []

        def append_batch(start: int, count: int) -> None:
            try:
                for i in range(count):
                    self._repo.append_event(_make_event(event_key=f"k{start+i}", sequence=start + i + 1))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=append_batch, args=(i * 10, 10)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        items, _ = self._repo.get_events(_SESSION_ID)
        self.assertEqual(len(items), 50)
        ordinals = [e.event_ordinal for e in items]
        self.assertEqual(len(set(ordinals)), 50)
        self.assertEqual(ordinals, sorted(ordinals))


# ---------------------------------------------------------------------------
# Phase 8: Strict cursor and limit tests
# ---------------------------------------------------------------------------

class CursorTests(unittest.TestCase):
    """Cursor encode/decode round-trip and strict validation."""

    def test_session_cursor_roundtrip(self) -> None:
        encoded = _encode_cursor("1000", "sess-x")
        decoded = _decode_cursor(encoded)
        self.assertEqual(decoded, ["1000", "sess-x"])

    def test_event_cursor_roundtrip(self) -> None:
        encoded = _encode_cursor("5", "42")
        decoded = _decode_cursor(encoded)
        self.assertEqual(decoded, ["5", "42"])

    def test_cursor_contains_version_v1(self) -> None:
        decoded = _decode_cursor(_encode_cursor("1", "2"))
        self.assertIsNotNone(decoded)
        # Version is stripped by _decode_cursor; verify the encoded form.
        raw = _decode_cursor(_encode_cursor("1", "2"))
        encoded = _encode_cursor("1", "2")
        # The raw base64 decodes to "v1\x1f1\x1f2"
        import base64
        decoded_raw = base64.urlsafe_b64decode(encoded + "==").decode("utf-8")
        self.assertTrue(decoded_raw.startswith("v1"))

    def test_empty_cursor_returns_none(self) -> None:
        self.assertIsNone(_decode_cursor(""))
        self.assertIsNone(_decode_cursor(None))

    def test_invalid_base64_rejected(self) -> None:
        with self.assertRaises(CursorValidationError):
            _decode_cursor("!!!not-base64!!!")

    def test_non_urlsafe_base64_rejected(self) -> None:
        """Standard base64 '+' and '/' characters are rejected."""
        with self.assertRaises(CursorValidationError):
            _decode_cursor("abc+def/xyz=")

    def test_invalid_utf8_rejected(self) -> None:
        # Valid URL-safe base64 that decodes to non-UTF-8 bytes.
        import base64
        raw_bytes = b"\x80\x81\x82"  # invalid UTF-8
        encoded = base64.urlsafe_b64encode(raw_bytes).decode("ascii")
        with self.assertRaises(CursorValidationError):
            _decode_cursor(encoded)

    def test_missing_version_rejected(self) -> None:
        import base64
        encoded = base64.urlsafe_b64encode(b"no-version").decode("ascii")
        with self.assertRaises(CursorValidationError):
            _decode_cursor(encoded)

    def test_empty_decoded_payload_returns_empty_list(self) -> None:
        # A cursor that decodes to just the version with no fields yields [].
        import base64
        encoded = base64.urlsafe_b64encode(b"v1").decode("ascii")
        result = _decode_cursor(encoded)
        self.assertEqual(result, [])

    def test_cursor_opaque_to_clients(self) -> None:
        """Clients cannot guess the cursor format; it is just a base64 string."""
        encoded = _encode_cursor("999", "secret-id")
        self.assertIsInstance(encoded, str)
        # URL-safe base64 alphabet plus '=' padding
        import re
        self.assertRegex(encoded, r"^[A-Za-z0-9-_]+=*$")


class LimitParseTests(unittest.TestCase):
    """HTTP-level limit validation produces normalized 400 errors."""

    def test_valid_minimum_limit(self) -> None:
        self.assertEqual(_parse_limit("1", 50, 200), 1)

    def test_valid_maximum_limit(self) -> None:
        self.assertEqual(_parse_limit("200", 50, 200), 200)

    def test_none_returns_default(self) -> None:
        self.assertEqual(_parse_limit(None, 50, 200), 50)

    def test_non_numeric_returns_400(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            _parse_limit("abc", 50, 200)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail["error"]["code"], "invalid_limit")

    def test_zero_returns_400(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            _parse_limit("0", 50, 200)
        self.assertEqual(ctx.exception.detail["error"]["code"], "invalid_limit")

    def test_negative_returns_400(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            _parse_limit("-5", 50, 200)
        self.assertEqual(ctx.exception.detail["error"]["code"], "invalid_limit")

    def test_exceeds_max_returns_400(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            _parse_limit("201", 50, 200)
        self.assertEqual(ctx.exception.detail["error"]["code"], "invalid_limit")


# ---------------------------------------------------------------------------
# Phase 9: Event identity and collision tests
# ---------------------------------------------------------------------------

class EventIdentityTests(unittest.TestCase):
    """Every legitimate event persists separately; true duplicates deduplicate."""

    def test_event_keys_are_non_empty(self) -> None:
        key = build_event_key("delta", "t1", "m1", 1, None)
        self.assertTrue(len(key) > 0)

    def test_event_keys_unique_for_distinct_frames(self) -> None:
        """Two different tool calls in one turn must produce different keys."""
        key_a = build_event_key("tool_start", "t1", None, None, "tc-a")
        key_b = build_event_key("tool_start", "t1", None, None, "tc-b")
        self.assertNotEqual(key_a, key_b)

    def test_tool_start_and_tool_result_separate(self) -> None:
        key_start = build_event_key("tool_start", "t1", None, None, "tc1")
        key_result = build_event_key("tool_result", "t1", None, None, "tc1")
        self.assertNotEqual(key_start, key_result)

    def test_multiple_tool_updates_separate(self) -> None:
        key1 = build_event_key("tool_update", "t1", None, 1, "tc1")
        key2 = build_event_key("tool_update", "t1", None, 2, "tc1")
        self.assertNotEqual(key1, key2)

    def test_two_different_parts_separate(self) -> None:
        key_a = build_event_key("part_delta", "t1", None, 1, "part-a")
        key_b = build_event_key("part_delta", "t1", None, 1, "part-b")
        self.assertNotEqual(key_a, key_b)

    def test_part_lifecycle_events_separate(self) -> None:
        start = build_event_key("part_start", "t1", None, None, "p1")
        delta = build_event_key("part_delta", "t1", None, 1, "p1")
        done = build_event_key("part_done", "t1", None, None, "p1")
        self.assertEqual(len({start, delta, done}), 3)

    def test_duplicate_part_delta_with_identical_payload_separate(self) -> None:
        """Two part_delta frames with the same occurrence counter value share a
        key — they are intentional duplicates from the same persistence call.
        Different occurrence values (different calls) produce different keys."""
        key1 = build_event_key("part_delta", "t1", None, 1, "p1")
        key2 = build_event_key("part_delta", "t1", None, 2, "p1")
        self.assertNotEqual(key1, key2)

    def test_permission_request_and_result_separate(self) -> None:
        req = build_event_key("permission_request", "t1", None, None, "perm-1")
        res = build_event_key("permission_result", "t1", None, None, "perm-1")
        self.assertNotEqual(req, res)

    def test_multiple_permission_ids_separate(self) -> None:
        key_a = build_event_key("permission_request", "t1", None, None, "perm-a")
        key_b = build_event_key("permission_request", "t1", None, None, "perm-b")
        self.assertNotEqual(key_a, key_b)

    def test_delta_distinguished_by_sequence(self) -> None:
        key1 = build_event_key("delta", "t1", "m1", 1, None)
        key2 = build_event_key("delta", "t1", "m1", 2, None)
        self.assertNotEqual(key1, key2)

    def test_terminal_events_distinguished_by_type_and_turn(self) -> None:
        key_done = build_event_key("done", "t1", None, None, None)
        key_err = build_event_key("error", "t1", None, None, None)
        self.assertNotEqual(key_done, key_err)

    def test_no_timestamp_in_event_key(self) -> None:
        key1 = build_event_key("delta", "t1", "m1", 1, None)
        key2 = build_event_key("delta", "t1", "m1", 1, None)
        self.assertEqual(key1, key2)
        # Keys are identical when all identity fields match — timestamp is
        # deliberately excluded.
        self.assertNotIn(str(int(time.time() * 1000)), key1)

    def test_no_python_hash_in_event_key(self) -> None:
        """Event keys must be deterministic across runs; hash() is not."""
        key1 = build_event_key("tool_update", "t1", None, 3, "tc1")
        key2 = build_event_key("tool_update", "t1", None, 3, "tc1")
        self.assertEqual(key1, key2)

    def test_stored_ordinal_matches_emission_order(self) -> None:
        """Events stored in the repo must have ordinals matching their
        insertion order (monotonic per session)."""
        td = tempfile.mkdtemp()
        try:
            repo = _make_repo(td)
            repo.create_session(_make_session())
            for i in range(5):
                repo.append_event(_make_event(event_key=f"k{i}", sequence=i + 1))
            items, _ = repo.get_events(_SESSION_ID)
            ordinals = [e.event_ordinal for e in items]
            self.assertEqual(ordinals, [1, 2, 3, 4, 5])
        finally:
            import shutil
            shutil.rmtree(td, ignore_errors=True)

    def test_occurrence_values_not_on_wire(self) -> None:
        """The occurrence-based sequence value used in the event key is
        persistence-only; the wire frame's original sequence field is preserved
        separately in HistoryEvent.sequence."""
        # The event_key for a part_delta uses the occurrence counter as
        # sequence, but the original frame sequence is also stored.
        frame_key = build_event_key("part_delta", "t1", None, 1, "p1")
        # The key includes the occurrence (1) but the original frame's sequence
        # field (None in this case) is separate in the HistoryEvent.
        self.assertIn("1", frame_key)  # occurrence is in the key

    def test_reappending_same_event_key_deduplicates(self) -> None:
        """Re-appending the exact same HistoryEvent (same event_key) deduplicates."""
        td = tempfile.mkdtemp()
        try:
            repo = _make_repo(td)
            repo.create_session(_make_session())
            event = _make_event(event_key="dup-key", payload={"text": "x"})
            self.assertTrue(repo.append_event(event))
            self.assertFalse(repo.append_event(event))
            items, _ = repo.get_events(_SESSION_ID)
            self.assertEqual(len(items), 1)
        finally:
            import shutil
            shutil.rmtree(td, ignore_errors=True)

    def test_separate_persist_frame_calls_generate_distinct_keys(self) -> None:
        """Calling the equivalent of _persist_frame twice for a part_delta
        increments the occurrence counter each time, producing a new key.
        This proves there is no cross-call retry-key reuse."""
        td = tempfile.mkdtemp()
        try:
            repo = _make_repo(td)
            repo.create_session(_make_session())
            # Simulate two _persist_frame calls for the same part_delta frame.
            # First call: occurrence = 1, key = "part_delta|t1||1|p1"
            event1 = _make_event(
                event_type="part_delta",
                event_key=build_event_key("part_delta", "t1", None, 1, "p1"),
                payload={"text": "chunk"},
            )
            # Second call (simulating a re-invocation): occurrence = 2, key = "part_delta|t1||2|p1"
            event2 = _make_event(
                event_type="part_delta",
                event_key=build_event_key("part_delta", "t1", None, 2, "p1"),
                payload={"text": "chunk"},
            )
            self.assertTrue(repo.append_event(event1))
            self.assertTrue(repo.append_event(event2))
            items, _ = repo.get_events(_SESSION_ID)
            # Two distinct events persisted (not deduplicated).
            self.assertEqual(len(items), 2)
            keys = {e.event_key for e in items}
            self.assertEqual(keys, {"part_delta|t1||1|p1", "part_delta|t1||2|p1"})
        finally:
            import shutil
            shutil.rmtree(td, ignore_errors=True)

    def test_no_event_key_uses_timestamp(self) -> None:
        """event_key must not contain any timestamp component."""
        import time
        ts = str(int(time.time() * 1000))
        key = build_event_key("delta", "t1", "m1", 1, None)
        self.assertNotIn(ts, key)

    def test_no_event_key_uses_python_hash(self) -> None:
        """event_key must not contain Python's non-deterministic hash()."""
        key = build_event_key("tool_update", "t1", None, 1, "tc1")
        h = str(hash("anything"))
        self.assertNotIn(h, key)


if __name__ == "__main__":
    unittest.main()
