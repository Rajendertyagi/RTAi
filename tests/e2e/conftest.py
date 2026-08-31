"""Conftest for Playwright E2E tests — provides a real FastAPI server fixture."""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

# Ensure backend is importable.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.logging_config import configure_logging  # noqa: E402
from app.main import create_app  # noqa: E402

# Capture structured backend logs for CI failure artifacts.  The file lives
# under test-results/ which the workflow uploads when a Playwright job fails.
_TEST_RESULTS = REPO_ROOT / "test-results"
_TEST_RESULTS.mkdir(exist_ok=True)
configure_logging(
    level=os.environ.get("RTAI_LOG_LEVEL", "DEBUG"),
    filename=str(_TEST_RESULTS / "backend.log"),
)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def server_url():
    """Start a real FastAPI server on a free port for Playwright to hit.

    When RTAI_TEST_ADAPTER=fake, injects a deterministic fake adapter so the
    test never touches OpenCode or model credentials.
    """
    port = _free_port()
    url = f"http://127.0.0.1:{port}"

    adapter_factory = None
    if os.environ.get("RTAI_TEST_ADAPTER") == "fake":
        import asyncio  # noqa: E402

        from unittest.mock import MagicMock  # noqa: E402

        from app.agents.base import AgentAdapter, SelectionResult  # noqa: E402
        from app.agents.capabilities import (  # noqa: E402
            AgentDescriptor,
            CapabilitySection,
            CapabilitySnapshot,
        )

        class FakeAdapter(AgentAdapter):
            def __init__(self) -> None:
                self._emit = None
                self._cancelled = False
                self._snap = CapabilitySnapshot(
                    source="fake",
                    agent=AgentDescriptor(id="fake-agent", label="FakeAgent"),
                    agents=CapabilitySection(
                        items=(
                            MagicMock(id="fake-agent", label="FakeAgent"),
                        )
                    ),
                    models=CapabilitySection(
                        items=(
                            MagicMock(id="m-fast", label="Fast"),
                            MagicMock(id="m-deep", label="Deep and Reasoning-Extended"),
                        )
                    ),
                    modes=CapabilitySection(items=(MagicMock(id="ask", label="Ask"), MagicMock(id="code", label="Code Assistant Pro Mode"))),
                    thinking_options=CapabilitySection(items=(MagicMock(id="off", label="Off"), MagicMock(id="low", label="Low Effort"), MagicMock(id="medium", label="Medium Effort"), MagicMock(id="high", label="High Effort Extended"))),
                )

            async def start(self, cwd, emit):  # type: ignore[override]
                self._emit = emit
                await emit({"type": "status", "state": "starting", "cwd": str(cwd)})
                await emit({"type": "agent_info", "name": "FakeAgent"})
                await emit({
                    "type": "agents_available",
                    "agents": [{"id": "fake-agent", "label": "FakeAgent"}],
                })
                await emit({
                    "type": "models_available",
                    "models": [
                        {"id": "m-fast", "label": "Fast"},
                        {"id": "m-deep", "label": "Deep and Reasoning-Extended"},
                    ],
                })
                await emit({
                    "type": "modes_available",
                    "modes": [{"id": "ask", "label": "Ask"}, {"id": "code", "label": "Code Assistant Pro Mode"}],
                })
                await emit({"type": "thinking_available", "thinking_levels": ["off", "low", "medium", "high"]})
                await emit({"type": "status", "state": "ready", "cwd": str(cwd)})

            async def close(self) -> None:
                pass

            def capability_snapshot(self):
                return self._snap

            async def submit_prompt(self, text: str) -> None:
                """Stream a deterministic markdown reply, then finalize.

                Cancellable: a mid-stream ``cancel()`` or task cancellation stops
                the loop; the routes layer emits the terminal ``done`` event.
                """
                self._cancelled = False
                if self._emit is None:
                    return
                document = "\n".join([
                    "# RTAI Deterministic Response",
                    "",
                    "This is a **streamed** assistant reply used by the E2E suite.",
                    "",
                    "## Features",
                    "",
                    "- Streaming text rendering",
                    "- Markdown support everywhere",
                    "- Inline `code` snippets work",
                    "",
                    "### Steps",
                    "",
                    "1. Connect to the WebSocket",
                    "2. Submit a prompt",
                    "3. Receive streamed deltas",
                    "",
                    "> A blockquote kept for layout verification.",
                    "",
                    "See the [documentation](https://example.com) for details.",
                    "",
                    "```python",
                    "def greet(name: str) -> str:",
                    '    return f"hello {name}"',
                    "```",
                    "",
                    "Final paragraph with extra words so the stream visibly grows "
                    "over time, giving the auto-scroll and growth assertions "
                    "something observable.",
                ])
                chunks: list[str] = []
                current = ""
                for word in document.split(" "):
                    if current and len(current) + len(word) + 1 > 24:
                        chunks.append(current + " ")
                        current = word
                    else:
                        current = (current + " " + word) if current else word
                if current:
                    chunks.append(current)
                for chunk in chunks:
                    if self._cancelled:
                        break
                    await self._emit({"type": "delta", "text": chunk})
                    await asyncio.sleep(0.04)
                if not self._cancelled:
                    await self._emit({"type": "done", "reason": "completed"})

            async def submit_prompt_content(self, content: list[Any]) -> None:
                pass

            async def cancel(self) -> None:
                self._cancelled = True

            def owned_process(self):
                return None

            async def select(self, kind: str, value_id: str) -> SelectionResult:
                return SelectionResult(kind=kind, applied=True, message="ok")

        fa = MagicMock()
        fa.create.return_value = FakeAdapter()
        adapter_factory = fa

    app = create_app(adapter_factory=adapter_factory)
    from app.api.routes import router  # noqa: E402
    app.include_router(router)

    import uvicorn  # noqa: E402

    # Logging is configured above (stderr + test-results/backend.log); uvicorn
    # must not apply its own config which would override our handlers.
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_config=None)
    server = uvicorn.Server(config)

    def _run():
        server.run()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    # Wait for the server to be ready.
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect(("127.0.0.1", port))
            break
        except OSError:
            time.sleep(0.1)
    else:
        raise RuntimeError(f"Server did not start on port {port}")

    yield url

    server.should_exit = True
    thread.join(timeout=5)
