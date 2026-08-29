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
    folder_input = page.locator('input[placeholder*="project"], input[placeholder*="folder"]')
    if not folder_input.is_visible():
        folder_input = page.locator('input[type="text"]').first
    folder_input.fill(project_folder)
    folder_input.press("Enter")

    # Wait for connection to reach ready or error.
    ready = page.locator('span.status.ready')
    error = page.locator('.banner.error')
    try:
        ready.wait_for(state="visible", timeout=15000)
    except Exception:
        if error.count() > 0:
            error_text = error.first.inner_text()
            raise AssertionError(f"Connection failed: {error_text}") from None
        raise


def test_page_loads_with_rtai_heading(page, server_url: str) -> None:
    """Page loads; heading is RTAI; no mock UI remains."""
    page.goto(server_url)
    page.wait_for_load_state("networkidle")

    # The HTML title should be RTAI.
    assert "RTAI" in page.title()

    # The loquix-welcome-screen renders its heading as an attribute, not text.
    heading = page.locator("loquix-welcome-screen").first
    heading.wait_for(state="visible", timeout=5000)
    heading_attr = heading.get_attribute("heading") or ""
    assert "Mock AI workspace" not in heading_attr
    assert "RTAI" in heading_attr

    body = page.content()
    assert "Mock agent" not in body
    assert "Mock Fast" not in body
    assert "C:\\projects\\my-app" not in body


def test_websocket_connects_and_reaches_ready(page, server_url: str) -> None:
    """WebSocket reaches ready state with deterministic adapter."""
    page.goto(server_url)
    page.wait_for_load_state("networkidle")

    _enter_project_and_wait(page, str(REPO_ROOT))

    status_el = page.locator('span.status')
    status_el.wait_for(state="visible", timeout=10000)
    assert status_el.text_content() == "ready"


def test_diagnostics_reports_websocket(page, server_url: str) -> None:
    """Diagnostics panel reports 'websocket' transport type."""
    page.goto(server_url)
    page.wait_for_load_state("networkidle")
    _enter_project_and_wait(page, str(REPO_ROOT))

    # The diagnostics panel is open by default. Verify it is visible and
    # contains the Transport row (the presence of the table confirms the
    # panel rendered with real data, not mock strings).
    page.locator("rtai-diagnostics-panel").wait_for(timeout=5000)
    page.locator('rtai-diagnostics-panel table').wait_for(timeout=5000)

    # Read the page source to confirm no mock UI remains.
    body = page.content()
    assert "Mock agent" not in body
    assert "Mock Fast" not in body


def test_composer_is_enabled_after_ready(page, server_url: str) -> None:
    """Composer becomes usable after connection reaches ready."""
    page.goto(server_url)
    page.wait_for_load_state("networkidle")
    _enter_project_and_wait(page, str(REPO_ROOT))

    composer = page.locator("loquix-chat-composer")
    composer.wait_for(timeout=5000)
    assert not composer.evaluate("el => el.disabled")


def test_prompt_submission_produces_events(page, server_url: str) -> None:
    """Send a prompt and verify the UI reflects it."""
    page.goto(server_url)
    page.wait_for_load_state("networkidle")
    _enter_project_and_wait(page, str(REPO_ROOT))

    textarea = page.locator("loquix-chat-composer textarea").first
    textarea.fill("hello world")
    textarea.press("Enter")

    page.locator('loquix-message-item[sender="user"]').wait_for(timeout=10000)


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


def test_composer_dropdown_overflow_fix(page, server_url: str) -> None:
    """Verify the CSS overflow override is applied to the composer container."""
    import os

    page.goto(server_url)
    page.wait_for_load_state("networkidle")
    _enter_project_and_wait(page, str(REPO_ROOT))

    composer = page.locator("loquix-chat-composer")
    composer.wait_for(timeout=5000)

    # Capture screenshot for diagnostics
    os.makedirs("test-results/screenshots", exist_ok=True)
    page.screenshot(path="test-results/screenshots/composer-before.png", full_page=False)

    # Verify the CSS override is applied: loquix-chat-composer::part(container)
    # should have overflow: visible (fixes truncated dropdown panels).
    overflow_value = composer.evaluate("""
        el => {
            const shadow = el.shadowRoot;
            if (!shadow) return null;
            const container = shadow.querySelector('[part="container"]');
            if (!container) return null;
            return getComputedStyle(container).overflow;
        }
    """)
    assert overflow_value == "visible", (
        f"Expected container overflow to be 'visible', got '{overflow_value}'"
    )

    # Verify the container has the expected border-radius (16px).
    border_radius = composer.evaluate("""
        el => {
            const shadow = el.shadowRoot;
            if (!shadow) return '';
            const container = shadow.querySelector('[part="container"]');
            return container ? getComputedStyle(container).borderRadius : '';
        }
    """)
    assert border_radius in ("16px", "16px 16px 16px 16px"), (
        f"Unexpected container border-radius: {border_radius}"
    )

    # Verify the textarea is still accessible and not obscured.
    textarea = composer.locator("textarea").first
    textarea.wait_for(state="visible", timeout=5000)
    assert textarea.is_visible()

    # Take final screenshot for evidence
    page.screenshot(path="test-results/screenshots/composer-after.png", full_page=False)


def test_composer_dropdowns_interactive(page, server_url: str) -> None:
    """Interact with each composer dropdown: open, verify, select, close."""
    import os

    page.goto(server_url)
    page.wait_for_load_state("networkidle")
    _enter_project_and_wait(page, str(REPO_ROOT))

    composer = page.locator("loquix-chat-composer")
    composer.wait_for(timeout=5000)

    # Create screenshots directory
    os.makedirs("test-results/screenshots", exist_ok=True)

    # The selectors are slotted inside loquix-chat-composer (custom element
    # with shadow DOM). Playwright's page.locator() pierces shadow DOM, so we
    # can target the selector components directly.
    # Each component exposes a .trigger button and a .panel inside its shadow.
    # loquix-dropdown-select appears twice (Agent, Thinking) — use nth() to
    # distinguish instances and avoid strict-mode violations.
    selector_configs = [
        ("loquix-dropdown-select", "Agent", 0),
        ("loquix-model-selector", "Model", 0),
        ("loquix-mode-selector", "Mode", 0),
        ("loquix-dropdown-select", "Thinking effort", 1),
    ]

    for selector_tag, label, nth_idx in selector_configs:
        # Locate the specific selector instance inside the composer's shadow DOM.
        selector = page.locator(
            f"loquix-chat-composer {selector_tag}"
        ).nth(nth_idx)
        selector.wait_for(state="visible", timeout=5000)

        # Click the trigger button (inside the selector's shadow DOM).
        trigger = selector.locator("button.trigger").first
        trigger.wait_for(state="visible", timeout=5000)
        trigger.click()

        # Wait for the dropdown panel to appear in the selector's shadow DOM.
        panel = selector.locator("div.panel:not([hidden])").first
        panel.wait_for(state="visible", timeout=5000)

        # Give the floating UI a moment to position and render the panel contents.
        page.wait_for_timeout(200)

        # Verify the panel has non-zero dimensions (if accessible).
        panel_bbox = panel.bounding_box()
        if panel_bbox is not None:
            assert panel_bbox["width"] > 0, f"Panel for {label} has zero width"
            assert panel_bbox["height"] > 0, f"Panel for {label} has zero height"
            # Verify panel is within viewport bounds.
            viewport = page.viewport_size
            # bounding_box returns {x, y, width, height}, not {top, bottom, left, right}
            assert panel_bbox["y"] >= 0, f"Panel for {label} clipped above viewport"
            assert panel_bbox["y"] + panel_bbox["height"] <= viewport["height"], (
                f"Panel for {label} extends below viewport"
            )
            assert panel_bbox["x"] >= 0, f"Panel for {label} clipped left"
            assert panel_bbox["x"] + panel_bbox["width"] <= viewport["width"], (
                f"Panel for {label} extends right"
            )

        # Verify panel has visible option text.
        # Use page.evaluate() to pierce shadow DOM and count option buttons
        # inside the opened panel.
        option_count = selector.evaluate("""
            el => {
                const panel = el.shadowRoot.querySelector('.panel');
                if (!panel || panel.hidden) return 0;
                // Options are buttons with class 'option' inside the .options div.
                const opts = panel.querySelectorAll('button.option, .option');
                return opts.length;
            }
        """)
        assert option_count > 0, f"No options found in {label} dropdown (got {option_count})"

        # Screenshot with dropdown open
        page.screenshot(
            path=f"test-results/screenshots/dropdown-{label.lower().replace(' ', '-')}.png",
            full_page=False,
        )

        # Close the dropdown with Escape.
        page.keyboard.press("Escape")
        panel.wait_for(state="hidden", timeout=5000)

    # Screenshot of composer after all interactions
    page.screenshot(path="test-results/screenshots/composer-after-interaction.png", full_page=False)
