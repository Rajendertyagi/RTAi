"""Backend unit tests.

Import bootstrap: puts ``<repo>/backend`` on ``sys.path`` so the test modules
can import ``app.*`` regardless of the working directory the discovery command
runs from. Needed on safe-path Pythons, which omit cwd from ``sys.path``
(same rationale as the bootstrap in ``backend/run.py``).
"""

import sys
from pathlib import Path

_BACKEND_DIR = str(Path(__file__).resolve().parents[2] / "backend")
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)
