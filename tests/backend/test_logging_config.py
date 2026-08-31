"""Structured logging configuration tests (RTAI_LOG_LEVEL, formatter, handlers)."""

from __future__ import annotations

import logging
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.logging_config import (
    EventFormatter,
    InvalidLogLevelError,
    build_logging_config,
    configure_logging,
    log_event,
    resolve_log_level,
    short_id,
)


def _reset_logging() -> None:
    """Restore a deterministic stderr-only INFO configuration."""
    configure_logging("INFO")


class ResolveLogLevelTests(unittest.TestCase):
    def test_default_level_is_info(self) -> None:
        self.assertEqual(resolve_log_level(None), "INFO")
        self.assertEqual(resolve_log_level(""), "INFO")
        self.assertEqual(resolve_log_level("   "), "INFO")

    def test_valid_levels_normalized(self) -> None:
        for raw, expected in (
            ("debug", "DEBUG"),
            ("INFO", "INFO"),
            ("warning", "WARNING"),
            ("error", "ERROR"),
            ("critical", "CRITICAL"),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(resolve_log_level(raw), expected)

    def test_invalid_level_raises_predictably(self) -> None:
        for raw in ("trace", "verbose", "bogus", "info2"):
            with self.subTest(raw=raw), self.assertRaises(InvalidLogLevelError):
                resolve_log_level(raw)

    def test_invalid_level_message_lists_valid_values(self) -> None:
        with self.assertRaises(InvalidLogLevelError) as ctx:
            resolve_log_level("trace")
        message = str(ctx.exception)
        self.assertIn("RTAI_LOG_LEVEL", message)
        self.assertIn("DEBUG", message)
        self.assertIn("CRITICAL", message)


class ShortIdTests(unittest.TestCase):
    def test_truncates_to_stable_prefix(self) -> None:
        self.assertEqual(short_id("session-1234567890"), "session-")
        self.assertEqual(short_id("abcdefghij"), "abcdefgh")

    def test_short_values_pass_through(self) -> None:
        self.assertEqual(short_id("abc"), "abc")

    def test_none_and_empty_are_safe(self) -> None:
        self.assertEqual(short_id(None), "")
        self.assertEqual(short_id(""), "")


class EventFormatterTests(unittest.TestCase):
    def test_formatter_emits_structured_line(self) -> None:
        record = logging.LogRecord(
            name="rtai.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="test_event",
            args=(),
            exc_info=None,
        )
        record.event = "test_event"
        record.meta = {"key": "value", "alpha": "1"}
        line = EventFormatter().format(record)
        self.assertIn("INFO", line)
        self.assertIn("rtai.test", line)
        self.assertIn("test_event", line)
        self.assertIn("alpha=1", line)
        self.assertIn("key=value", line)

    def test_formatter_tolerates_missing_extras(self) -> None:
        record = logging.LogRecord(
            name="rtai.test",
            level=logging.WARNING,
            pathname=__file__,
            lineno=1,
            msg="plain",
            args=(),
            exc_info=None,
        )
        line = EventFormatter().format(record)
        self.assertIn("WARNING", line)
        self.assertIn("plain", line)


class ConfigureLoggingTests(unittest.TestCase):
    def tearDown(self) -> None:
        _reset_logging()

    def test_configure_logging_returns_resolved_level(self) -> None:
        with mock.patch.dict(os.environ, {"RTAI_LOG_LEVEL": "DEBUG"}, clear=False):
            self.assertEqual(configure_logging(), "DEBUG")

    def test_configure_logging_defaults_to_info(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            self.assertEqual(configure_logging(), "INFO")

    def test_configure_logging_is_idempotent_no_duplicate_handlers(self) -> None:
        configure_logging("DEBUG")
        configure_logging("INFO")
        root = logging.getLogger()
        self.assertEqual(len(root.handlers), 1)
        self.assertEqual(root.level, logging.INFO)

    def test_uvicorn_loggers_propagate_to_root_without_handlers(self) -> None:
        configure_logging("INFO")
        for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "uvicorn.asgi"):
            with self.subTest(name=name):
                uvicorn_logger = logging.getLogger(name)
                self.assertEqual(uvicorn_logger.handlers, [])
                self.assertTrue(uvicorn_logger.propagate)

    def test_file_handler_added_when_filename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "backend.log"
            configure_logging("DEBUG", filename=str(log_path))
            root = logging.getLogger()
            self.assertEqual(len(root.handlers), 2)
            log_event(logging.getLogger("rtai.test"), logging.INFO, "file_event", k="v")
            for handler in root.handlers:
                handler.flush()
            content = log_path.read_text(encoding="utf-8")
            self.assertIn("file_event", content)
            self.assertIn("k=v", content)
            # Close the file handler so the temp dir can be removed on Windows.
            for handler in root.handlers:
                if isinstance(handler, logging.FileHandler):
                    handler.close()

    def test_build_logging_config_shape(self) -> None:
        config = build_logging_config("DEBUG", filename="x.log")
        self.assertEqual(config["version"], 1)
        self.assertFalse(config["disable_existing_loggers"])
        self.assertIn("stderr", config["handlers"])
        self.assertIn("file", config["handlers"])
        self.assertEqual(config["root"]["level"], "DEBUG")
        self.assertIn("uvicorn", config["loggers"])


if __name__ == "__main__":
    unittest.main()
