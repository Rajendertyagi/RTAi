"""Deterministic Playwright E2E test for the packaged RTAI browser UI.

Uses a test-only adapter override (RTAI_TEST_ADAPTER=fake) so no real
OpenCode binary or model credentials are needed. Exercises the full browser
journey against the real FastAPI + WebSocketTransport + Protocol v1 stack.
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import expect

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


def _submit_prompt(page, text: str) -> None:
    """Type a prompt and submit via Enter; wait for the user bubble."""
    textarea = page.locator(".composer-card textarea").first
    textarea.wait_for(state="visible", timeout=5000)
    textarea.fill(text)
    textarea.press("Enter")
    page.locator(".bubble--user").wait_for(timeout=10000)


def _wait_for_assistant(page, timeout: int = 15000) -> None:
    """Wait for the assistant bubble to appear."""
    page.locator(".bubble--assistant").wait_for(state="visible", timeout=timeout)


def test_page_loads_with_rtai_heading(page, server_url: str) -> None:
    """Page loads; title is RTAI Chat; empty state heading is visible."""
    page.goto(server_url)

    # The HTML title should reference RTAI.
    assert "RTAI" in page.title()

    # The empty state heading should be "How can I help?".
    heading = page.locator(".empty-state h1").first
    heading.wait_for(state="visible", timeout=10000)
    heading_text = heading.inner_text()
    assert "How can I help?" in heading_text

    body = page.content()
    assert "Mock agent" not in body
    assert "Mock Fast" not in body
    assert "C:\\projects\\my-app" not in body


def test_websocket_connects_and_reaches_ready(page, server_url: str) -> None:
    """WebSocket reaches ready state with deterministic adapter."""
    page.goto(server_url)
    _enter_project_and_wait(page, str(REPO_ROOT))

    status_bar = page.locator(".status-bar--persistent")
    status_bar.wait_for(state="visible", timeout=10000)
    status_text = status_bar.inner_text()
    assert "Ready" in status_text


def test_diagnostics_reports_websocket(page, server_url: str) -> None:
    """Status bar is visible and page has no mock UI."""
    page.goto(server_url)
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
    _enter_project_and_wait(page, str(REPO_ROOT))

    textarea = page.locator(".composer-card textarea").first
    textarea.wait_for(state="visible", timeout=5000)
    assert not textarea.evaluate("el => el.disabled")
    assert textarea.is_visible()


def test_prompt_submission_produces_events(page, server_url: str) -> None:
    """Send a prompt and verify the UI reflects it."""
    page.goto(server_url)
    _enter_project_and_wait(page, str(REPO_ROOT))

    textarea = page.locator(".composer-card textarea").first
    textarea.fill("hello world")
    textarea.press("Enter")

    page.locator(".bubble--user").wait_for(timeout=10000)


def test_api_routes_protected_from_spa_fallback(page, server_url: str) -> None:
    """/api/* returns JSON 404, not the SPA HTML fallback."""
    page.goto(server_url)
    base = server_url.rstrip("/")
    resp = page.evaluate(f"fetch('{base}/api/nonexistent').then(r => r.status)")
    assert resp == 404

    resp = page.evaluate(f"fetch('{base}/assets/nonexistent.js').then(r => r.status)")
    assert resp == 404


def test_no_unhandled_console_errors(page, server_url: str) -> None:
    """Browser has no unhandled page errors during a full streaming journey."""
    errors: list[str] = []
    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda err: errors.append(str(err)))

    page.goto(server_url)
    _enter_project_and_wait(page, str(REPO_ROOT))

    _submit_prompt(page, "trigger a full journey")
    _wait_for_assistant(page)
    # Wait for streaming to finish (send button returns to its idle arrow).
    page.locator(".composer__submit svg.lucide-arrow-up").wait_for(timeout=15000)

    assert errors == [], f"Unhandled console/page errors: {errors}"


def test_composer_layout_stable(page, server_url: str) -> None:
    """Verify the composer card is visible, has proper layout, and textarea is accessible."""
    page.goto(server_url)
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
    _enter_project_and_wait(page, str(REPO_ROOT))

    # Send a test message.
    textarea = page.locator(".composer-card textarea").first
    textarea.fill("test bubble rendering")
    textarea.press("Enter")

    # Wait for user bubble.
    user_bubble = page.locator(".bubble--user")
    user_bubble.wait_for(timeout=10000)
    assert user_bubble.inner_text() == "test bubble rendering"

    # The assistant response should also render (fake adapter streams it).
    assistant_bubble = page.locator(".bubble--assistant")
    expect(assistant_bubble).to_be_visible(timeout=15000)
    page_source = page.content()
    assert "bubble--assistant" in page_source
    assert "bubble--user" in page_source


# ── Structural / interaction proofs (required by the chat-layout fix) ─────────


def test_single_thread_footer_structure(page, server_url: str) -> None:
    """Exactly one sticky footer, owned by the viewport, holding status+composer."""
    page.goto(server_url)
    _enter_project_and_wait(page, str(REPO_ROOT))

    footers = page.locator(".thread-footer")
    expect(footers).to_have_count(1)
    # data-testid forwarded by the primitive.
    expect(page.locator('[data-testid="thread-viewport-footer"]')).to_have_count(1)

    viewport = page.locator(".chat__messages")
    expect(viewport.locator(".thread-footer")).to_have_count(1)

    footer = footers.first
    expect(footer.locator(".composer-card")).to_have_count(1)
    expect(footer.locator(".status-bar--persistent")).to_have_count(1)
    # No nested footer.
    expect(footer.locator(".thread-footer")).to_have_count(0)

    # Sticky positioning keeps it pinned to the viewport bottom.
    position = footer.evaluate("el => getComputedStyle(el).position")
    assert position == "sticky", f"expected sticky, got {position}"

    expect(footer).to_be_visible()
    # After scrolling the message list, the footer must remain visible.
    page.locator(".chat__messages").evaluate("el => { el.scrollTop = el.scrollHeight; }")
    expect(footer).to_be_visible()


def test_enter_submits_once(page, server_url: str) -> None:
    """Pressing Enter submits exactly one user message."""
    page.goto(server_url)
    _enter_project_and_wait(page, str(REPO_ROOT))

    textarea = page.locator(".composer-card textarea").first
    textarea.fill("single submit check")
    textarea.press("Enter")

    user_bubbles = page.locator(".bubble--user")
    expect(user_bubbles).to_have_count(1)
    expect(user_bubbles.first).to_contain_text("single submit check")


def test_shift_enter_newline_no_submit(page, server_url: str) -> None:
    """Shift+Enter inserts a newline and does NOT submit the prompt."""
    page.goto(server_url)
    _enter_project_and_wait(page, str(REPO_ROOT))

    textarea = page.locator(".composer-card textarea").first
    textarea.fill("line one")
    textarea.press("Shift+Enter")

    expect(page.locator(".bubble--user")).to_have_count(0)


def test_empty_input_no_submit(page, server_url: str) -> None:
    """Whitespace-only input must not produce a user message."""
    page.goto(server_url)
    _enter_project_and_wait(page, str(REPO_ROOT))

    textarea = page.locator(".composer-card textarea").first
    textarea.fill("    ")
    textarea.press("Enter")

    expect(page.locator(".bubble--user")).to_have_count(0)


def test_assistant_visible_bounding_box(page, server_url: str) -> None:
    """Assistant bubble is visible with non-zero size and real colors, in both themes."""
    page.goto(server_url)
    _enter_project_and_wait(page, str(REPO_ROOT))

    _submit_prompt(page, "show me a response")
    _wait_for_assistant(page)

    bubble = page.locator(".bubble--assistant").first
    expect(bubble).to_be_visible()

    bbox = bubble.bounding_box()
    assert bbox is not None
    assert bbox["width"] > 0
    assert bbox["height"] > 0

    # Force each theme and confirm the bubble stays visible and opaque.
    for forced in ("dark", "light"):
        page.evaluate(
            "t => { document.documentElement.dataset.theme = t;"
            " document.documentElement.style.colorScheme = t; }",
            forced,
        )
        expect(bubble).to_be_visible()
        bg = bubble.evaluate("el => getComputedStyle(el).backgroundColor")
        opacity = bubble.evaluate("el => getComputedStyle(el).opacity")
        assert float(opacity) > 0, f"assistant invisible (opacity) in {forced} theme"
        assert bg not in ("rgba(0, 0, 0, 0)", "transparent"), (
            f"assistant background invisible in {forced} theme: {bg}"
        )


def test_markdown_semantic_elements(page, server_url: str) -> None:
    """The streamed markdown renders all seven required semantic elements."""
    page.goto(server_url)
    _enter_project_and_wait(page, str(REPO_ROOT))

    _submit_prompt(page, "render markdown please")
    _wait_for_assistant(page)

    content = page.locator(".message__content").first
    expect(content).to_be_visible()
    # Wait for the stream to finish so every element is present.
    expect(content.locator("pre")).to_be_visible(timeout=15000)

    expect(content.locator("h1")).to_have_count(1)
    expect(content.locator("h2")).to_have_count(1)
    expect(content.locator("h3")).to_have_count(1)
    expect(content.locator("ul li")).to_have_count(3)
    expect(content.locator("ol li")).to_have_count(3)
    expect(content.locator("a")).to_have_count(1)
    expect(content.locator("blockquote")).to_have_count(1)
    expect(content.locator("code")).to_have_count(2)  # inline + fenced
    expect(content.locator("pre")).to_have_count(1)


def test_streaming_growth_auto_scroll(page, server_url: str) -> None:
    """Assistant text grows during streaming and the footer stays visible."""
    page.set_viewport_size({"width": 600, "height": 500})
    page.goto(server_url)
    _enter_project_and_wait(page, str(REPO_ROOT))

    textarea = page.locator(".composer-card textarea").first
    textarea.fill("grow the response")
    textarea.press("Enter")

    bubble = page.locator(".bubble--assistant").first
    expect(bubble).to_be_visible()

    first_len = len(bubble.inner_text())
    # Wait for streaming to finish (send button returns to its idle arrow).
    page.locator(".composer__submit svg.lucide-arrow-up").wait_for(timeout=15000)
    later_len = len(bubble.inner_text())
    assert later_len > first_len, "assistant text did not grow during streaming"

    # The sticky footer remains visible while content scrolls.
    expect(page.locator(".thread-footer")).to_be_visible()
    scrolled = page.locator(".chat__messages").evaluate("el => el.scrollTop > 0")
    assert scrolled, "message list did not scroll during streaming"


def test_responsive_no_horizontal_clip(page, server_url: str) -> None:
    """At a narrow width there is no horizontal overflow and key UI stays visible."""
    page.set_viewport_size({"width": 380, "height": 720})
    page.goto(server_url)
    _enter_project_and_wait(page, str(REPO_ROOT))

    _submit_prompt(page, "narrow viewport check")
    _wait_for_assistant(page)

    overflow = page.evaluate(
        "() => document.documentElement.scrollWidth <= window.innerWidth"
    )
    assert overflow, "horizontal overflow detected at narrow width"

    expect(page.locator(".thread-footer")).to_be_visible()
    expect(page.locator(".bubble--assistant").first).to_be_visible()


def test_cancel_during_streaming(page, server_url: str) -> None:
    """Clicking Stop mid-stream halts generation."""
    page.goto(server_url)
    _enter_project_and_wait(page, str(REPO_ROOT))

    textarea = page.locator(".composer-card textarea").first
    textarea.fill("cancel me mid stream")
    textarea.press("Enter")

    # Wait until streaming starts (stop icon appears).
    stop_icon = page.locator(".composer__submit svg.lucide-stop-circle")
    expect(stop_icon).to_be_visible(timeout=10000)

    bubble = page.locator(".bubble--assistant").first
    length_before = len(bubble.inner_text())
    assert length_before > 0

    page.locator(".composer__submit").click()

    # After cancel, the run stops: idle arrow returns.
    expect(page.locator(".composer__submit svg.lucide-arrow-up")).to_be_visible(timeout=10000)

    length_after = len(bubble.inner_text())
    page.wait_for_timeout(400)
    length_final = len(bubble.inner_text())
    assert length_final == length_after, "assistant kept streaming after cancel"
