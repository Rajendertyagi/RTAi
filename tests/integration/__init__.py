"""Real OpenCode compatibility integration tests.

Import bootstrap: puts ``<repo>/backend`` on ``sys.path`` so the test modules
can import ``app.*`` regardless of the working directory the discovery command
runs from.  Mirrors the bootstrap in ``tests/backend/__init__.py``.
"""

import sys
from pathlib import Path

_BACKEND_DIR = str(Path(__file__).resolve().parents[2] / "backend")
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)
