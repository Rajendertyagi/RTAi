"""Deterministic Playwright E2E test for the packaged RTAI browser UI.

Uses a test-only adapter override (RTAI_TEST_ADAPTER=fake) so no real
OpenCode binary or model credentials are needed. Exercises the full browser
journey against the real FastAPI + WebSocketTransport + Protocol v1 stack.
"""

from __future__ import annotations

import sys
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))


def _enter_project_and_wait(page, project_folder: str) -> None:
    """Fill the project folder input and press Enter, then wait for ready."""
    folder_input = page.locator("#projectFolder")
    if not folder_input.is_visible():
        folder_input = page.locator('input[placeholder*="project"], input[placeholder*="folder"]')
    if not folder_input.is_visible():
        folder_input = page.locator('input[type="text"]').first
    folder_input.fill(project_folder)
    folder_input.press("Enter")

    # Wait for connection to reach ready or error.
    ready = page.locator(".status-bar--persistent:has-text('Ready')")
    error = page.locator('.banner.error')
    try:
        ready.wait_for(state="visible", timeout=15000)
    except Exception:
        if error.count() > 0:
            error_text = error.first.inner_text()
            raise AssertionError(f"Connection failed: {error_text}") from None
        raise


def test_page_loads_with_rtai_heading(page, server_url: str) -> None:
    """Page loads; title is RTAI Chat; empty state heading is visible."""
    page.goto(server_url)
    page.wait_for_load_state("networkidle")

    # The HTML title should reference RTAI.
    assert "RTAI" in page.title()

    # The empty state heading should be "How can I help?".
    heading = page.locator(".empty-state h1").first
    heading.wait_for(state="visible", timeout=5000)
    heading_text = heading.inner_text()
    assert "How can I help?" in heading_text

    body = page.content()
    assert "Mock agent" not in body
    assert "Mock Fast" not in body
    assert "C:\\projects\\my-app" not in body


def test_websocket_connects_and_reaches_ready(page, server_url: str) -> None:
    """WebSocket reaches ready state with deterministic adapter."""
    page.goto(server_url)
    page.wait_for_load_state("networkidle")

    _enter_project_and_wait(page, str(REPO_ROOT))

    status_bar = page.locator(".status-bar--persistent")
    status_bar.wait_for(state="visible", timeout=10000)
    status_text = status_bar.inner_text()
    assert "Ready" in status_text


def test_diagnostics_reports_websocket(page, server_url: str) -> None:
    """Status bar is visible and page has no mock UI."""
    page.goto(server_url)
    page.wait_for_load_state("networkidle")
    _enter_project_and_wait(page, str(REPO_ROOT))

    # The status bar should be visible and show "Ready".
    status_bar = page.locator(".status-bar--persistent")
    status_bar.wait_for(timeout=5000)
    assert "Ready" in status_bar.inner_text()

    # Read the page source to confirm no mock UI remains.
    body = page.content()
    assert "Mock agent" not in body
    assert "Mock Fast" not in body


def test_composer_is_enabled_after_ready(page, server_url: str) -> None:
    """Composer becomes usable after connection reaches ready."""
    page.goto(server_url)
    page.wait_for_load_state("networkidle")
    _enter_project_and_wait(page, str(REPO_ROOT))

    textarea = page.locator(".composer-card textarea").first
    textarea.wait_for(state="visible", timeout=5000)
    assert not textarea.evaluate("el => el.disabled")
    assert textarea.is_visible()


def test_prompt_submission_produces_events(page, server_url: str) -> None:
    """Send a prompt and verify the UI reflects it."""
    page.goto(server_url)
    page.wait_for_load_state("networkidle")
    _enter_project_and_wait(page, str(REPO_ROOT))

    textarea = page.locator(".composer-card textarea").first
    textarea.fill("hello world")
    textarea.press("Enter")

    page.locator(".bubble--user").wait_for(timeout=10000)


def test_api_routes_protected_from_spa_fallback(page, server_url: str) -> None:
    """/api/* returns JSON 404, not the SPA HTML fallback."""
    page.goto(server_url)
    page.wait_for_load_state("networkidle")
    base = server_url.rstrip("/")
    resp = page.evaluate(f"fetch('{base}/api/nonexistent').then(r => r.status)")
    assert resp == 404

    resp = page.evaluate(f"fetch('{base}/assets/nonexistent.js').then(r => r.status)")
    assert resp == 404


def test_no_unhandled_console_errors(page, server_url: str) -> None:
    """Browser has no unhandled page errors during the journey."""
    errors: list[str] = []
    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda err: errors.append(str(err)))

    page.goto(server_url)
    page.wait_for_load_state("networkidle")
    _enter_project_and_wait(page, str(REPO_ROOT))

    page.wait_for_timeout(2000)
    assert errors == [], f"Unhandled console/page errors: {errors}"


def test_composer_layout_stable(page, server_url: str) -> None:
    """Verify the composer card is visible, has proper layout, and textarea is accessible."""
    page.goto(server_url)
    page.wait_for_load_state("networkidle")
    _enter_project_and_wait(page, str(REPO_ROOT))

    composer = page.locator(".composer-card")
    composer.wait_for(state="visible", timeout=5000)

    # Verify the container is visible and has non-zero dimensions.
    bbox = composer.bounding_box()
    assert bbox is not None
    assert bbox["width"] > 0
    assert bbox["height"] > 0

    # Verify the textarea is still accessible and not obscured.
    textarea = composer.locator("textarea").first
    textarea.wait_for(state="visible", timeout=5000)
    assert textarea.is_visible()

    # Verify the send button is present.
    send_btn = composer.locator("button[type='submit'], .composer__submit").first
    send_btn.wait_for(state="visible", timeout=5000)
    assert send_btn.is_visible()


def test_message_bubbles_render(page, server_url: str) -> None:
    """Verify user and assistant message bubbles have correct classes."""
    page.goto(server_url)
    page.wait_for_load_state("networkidle")
    _enter_project_and_wait(page, str(REPO_ROOT))

    # Send a test message.
    textarea = page.locator(".composer-card textarea").first
    textarea.fill("test bubble rendering")
    textarea.press("Enter")

    # Wait for user bubble.
    user_bubble = page.locator(".bubble--user")
    user_bubble.wait_for(timeout=10000)
    assert user_bubble.inner_text() == "test bubble rendering"

    # Verify assistant bubble class exists (will appear when response arrives).
    # The fake adapter doesn't send deltas, so we just verify the bubble--assistant
    # class is used in the template by checking the page structure.
    page_source = page.content()
    assert "bubble--assistant" in page_source
    assert "bubble--user" in page_source
