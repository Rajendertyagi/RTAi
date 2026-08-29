"""Shared helpers for real OpenCode integration tests.

These tests require a real OpenCode Windows binary.  They are skipped unless
``OPENCODE_BIN`` points to an executable or ``opencode`` is on ``PATH``.  The
CI integration job downloads the pinned release, verifies its SHA-256, extracts
it, and sets ``OPENCODE_BIN`` before running the suite.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path


def opencode_bin_path() -> str | None:
    """Return the path to a real OpenCode binary, or ``None`` to skip."""
    env = os.environ.get("OPENCODE_BIN")
    if env and Path(env).is_file():
        return env
    found = shutil.which("opencode")
    if found:
        return found
    return None


def require_opencode_bin() -> str:
    """Return the binary path or raise ``unittest.SkipTest``."""
    import unittest

    path = opencode_bin_path()
    if path is None:
        raise unittest.SkipTest(
            "No real OpenCode binary available (set OPENCODE_BIN or put "
            "'opencode' on PATH). Real-binary integration runs in CI only."
        )
    return path


def make_temp_project_dir() -> tempfile.TemporaryDirectory[str]:
    """Create a unique, disposable project directory for one test run."""
    return tempfile.TemporaryDirectory(prefix="rtai-opencode-")
