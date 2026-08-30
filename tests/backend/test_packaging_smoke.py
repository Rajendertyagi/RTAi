"""Packaging and static-asset smoke tests.

These verify that FastAPI serves the built Loquix SPA correctly, that
/api routes return JSON 404s (not SPA HTML), and that the missing-build
diagnostic page is shown when dist/ is absent.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from app.agents.base import AgentAdapter, Emit, SelectionResult
from app.agents.capabilities import (
    AgentDescriptor,
    CapabilitySection,
    CapabilitySnapshot,
)
from app.api.routes import router
from app.main import create_app
from fastapi.testclient import TestClient


class FakeAdapter(AgentAdapter):
    def __init__(self) -> None:
        self._snap = CapabilitySnapshot(
            source="fake",
            agent=AgentDescriptor(id="fake", label="Fake"),
            models=CapabilitySection(items=()),
            modes=CapabilitySection(items=()),
            thinking_options=CapabilitySection(items=()),
        )

    async def start(self, cwd: Path, emit: Emit) -> None:
        pass

    async def close(self) -> None:
        pass

    def capability_snapshot(self) -> CapabilitySnapshot:
        return self._snap

    async def submit_prompt(self, text: str) -> None:
        pass

    async def cancel(self) -> None:
        pass

    def owned_process(self):
        return None

    async def select(self, kind: str, value_id: str) -> SelectionResult:
        return SelectionResult(kind=kind, applied=True, message="ok")


def _make_client_with_dist(dist_dir: Path) -> TestClient:
    """Create a TestClient whose BASE_DIR points at dist_dir.parent."""
    import app.main as main_module
    original = main_module.BASE_DIR
    main_module.BASE_DIR = dist_dir.parent
    try:
        app = create_app(adapter_factory=MagicMock(create=lambda: FakeAdapter()))
        app.include_router(router)
        return TestClient(app)
    finally:
        main_module.BASE_DIR = original


def _make_client_no_dist() -> TestClient:
    """Create a TestClient with no static/dist directory."""
    import app.main as main_module
    original = main_module.BASE_DIR
    # Point at a non-existent directory.
    fake_base = Path(tempfile.mkdtemp()) / "no_such_dir"
    main_module.BASE_DIR = fake_base
    try:
        app = create_app(adapter_factory=MagicMock(create=lambda: FakeAdapter()))
        app.include_router(router)
        return TestClient(app)
    finally:
        main_module.BASE_DIR = original
        shutil.rmtree(fake_base.parent, ignore_errors=True)


def _setup_dist(base: Path) -> Path:
    """Create a minimal dist/ tree under base and return base / dist."""
    dist = base / "static" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text('<!doctype html><rtai-app></rtai-app>')
    assets = dist / "assets"
    assets.mkdir()
    (assets / "app.js").write_text("// dummy")
    return dist


class StaticAssetTests(unittest.TestCase):
    def test_get_root_serves_index_html_when_dist_present(self) -> None:
        base = Path(tempfile.mkdtemp())
        try:
            _setup_dist(base)
            client = _make_client_with_dist(base / "static")
            resp = client.get("/")
            self.assertEqual(resp.status_code, 200)
            self.assertIn("rtai-app", resp.text)
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_get_root_returns_diagnostic_when_dist_missing(self) -> None:
        client = _make_client_no_dist()
        resp = client.get("/")
        self.assertEqual(resp.status_code, 404)
        self.assertIn("Frontend build is missing", resp.text)
        self.assertNotIn("deep-chat", resp.text)
        self.assertNotIn("rtai-app", resp.text)

    def test_api_health_returns_json(self) -> None:
        client = _make_client_no_dist()
        resp = client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok"})

    def test_api_unknown_route_returns_json_404_not_html(self) -> None:
        client = _make_client_no_dist()
        resp = client.get("/api/nope")
        self.assertEqual(resp.status_code, 404)
        ct = resp.headers.get("content-type", "")
        self.assertIn("application/json", ct)
        self.assertNotIn("rtai-app", resp.text)
        self.assertNotIn("deep-chat", resp.text)

    def test_missing_asset_returns_404_not_index_html(self) -> None:
        base = Path(tempfile.mkdtemp())
        try:
            _setup_dist(base)
            client = _make_client_with_dist(base / "static")
            resp = client.get("/assets/nonexistent.js")
            self.assertEqual(resp.status_code, 404)
            self.assertNotIn("rtai-app", resp.text)
        finally:
            shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
