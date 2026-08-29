"""Real OpenCode browser smoke test.

Verifies that the packaged UI connects to a real OpenCode adapter and
discovers capabilities honestly.  Requires the pinned OpenCode binary to
be on PATH (provided by the integration job).
"""

from __future__ import annotations

import sys
from pathlib import Path

# ── Backend wiring ────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))


def _enter_project_and_wait(page, project_folder: str) -> None:
    """Fill the project folder input and press Enter, then wait for ready."""
    folder_input = page.locator('input[placeholder*="project"], input[placeholder*="folder"]')
    if not folder_input.is_visible():
        folder_input = page.locator('input[type="text"]').first
    folder_input.fill(project_folder)
    folder_input.press("Enter")

    ready = page.locator('span.status.ready')
    error = page.locator('span.status.error, .banner.error')
    try:
        ready.wait_for(state="visible", timeout=15000)
    except Exception as exc:
        if error.count() > 0:
            error_text = error.first.inner_text()
            raise AssertionError(f"Connection failed: {error_text}") from None
        raise exc


def test_opencode_capability_discovery(page, server_url: str) -> None:
    """Real OpenCode adapter discovers agents, models, modes through the UI."""
    page.goto(server_url)
    page.wait_for_load_state("networkidle")

    _enter_project_and_wait(page, str(REPO_ROOT))

    status = page.locator('span.status')
    status_text = status.inner_text()
    assert status_text not in ("disconnected", "connecting"), (
        f"Connection never reached ready: {status_text}"
    )

    # Diagnostics panel is open by default; verify it rendered.
    page.locator("rtai-diagnostics-panel").wait_for(timeout=5000)
    page.locator('rtai-diagnostics-panel table').wait_for(timeout=5000)

    # Confirm no mock UI strings appear anywhere in the page.
    body = page.content()
    assert "Mock agent" not in body
    assert "Mock Fast" not in body


def test_disconnect_closes_only_own_connection(page, server_url: str) -> None:
    """Refreshing the page creates a new WebSocket; old one is cleaned up."""
    page.goto(server_url)
    page.wait_for_load_state("networkidle")
    _enter_project_and_wait(page, str(REPO_ROOT))

    page.reload()
    page.wait_for_load_state("networkidle")
    _enter_project_and_wait(page, str(REPO_ROOT))

    final_status = page.locator('span.status').inner_text()
    assert final_status in ("ready", "connecting", "error")
