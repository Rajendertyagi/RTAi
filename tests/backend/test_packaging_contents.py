"""Runtime-package content tests.

These verify that the ``rtai-web-package`` artifact contains exactly the files
needed to run the backend plus the packaged frontend, and nothing else.  They
run in the CI packaging job against the staged package directory pointed to by
``RTAI_PACKAGE_DIR`` and skip locally where no staged package exists.
"""

from __future__ import annotations

import os
import re
import unittest
from pathlib import Path

_PACKAGE_DIR = os.environ.get("RTAI_PACKAGE_DIR")


@unittest.skipUnless(_PACKAGE_DIR, "RTAI_PACKAGE_DIR not set (CI packaging job only)")
class PackageContentsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pkg = Path(_PACKAGE_DIR or "").resolve()

    def test_runtime_requirements_present(self) -> None:
        req = self.pkg / "backend" / "requirements.txt"
        self.assertTrue(req.is_file(), "requirements.txt missing from package")
        text = req.read_text(encoding="utf-8")
        for dep in ("fastapi", "uvicorn", "agent-client-protocol"):
            self.assertIn(dep, text)

    def test_dev_requirements_excluded(self) -> None:
        self.assertFalse(
            (self.pkg / "backend" / "requirements-dev.txt").exists(),
            "requirements-dev.txt must not ship in the runtime package",
        )

    def test_build_metadata_excluded(self) -> None:
        self.assertFalse(
            (self.pkg / "backend" / "pyproject.toml").exists(),
            "pyproject.toml is dev tooling config and must not ship",
        )

    def test_run_entrypoint_present(self) -> None:
        self.assertTrue((self.pkg / "backend" / "run.py").is_file())

    def test_required_python_modules_present(self) -> None:
        for rel in (
            "app/main.py",
            "app/api/routes.py",
            "app/api/protocol_v1.py",
            "app/core/protocol.py",
            "app/agents/base.py",
            "app/agents/factory.py",
            "app/agents/capabilities.py",
            "app/agents/owned_process.py",
            "app/agents/runtime_settings.py",
            "app/agents/opencode_acp.py",
            "app/logging_config.py",
        ):
            self.assertTrue(
                (self.pkg / "backend" / rel).is_file(), f"{rel} missing from package"
            )

    def test_packaged_frontend_present(self) -> None:
        self.assertTrue(
            (self.pkg / "backend" / "app" / "static" / "dist" / "index.html").is_file(),
            "packaged frontend dist/index.html missing",
        )

    def test_legacy_poc_assets_excluded(self) -> None:
        static = self.pkg / "backend" / "app" / "static"
        for name in ("chat.html", "chat.js", "chat.css"):
            self.assertFalse((static / name).exists(), f"{name} must not ship")

    def test_no_vcs_cache_or_env_files(self) -> None:
        for bad in (".git", "__pycache__", ".env"):
            self.assertFalse((self.pkg / "backend" / bad).exists(), f"{bad} must not ship")

    def test_no_tests_in_package(self) -> None:
        self.assertFalse((self.pkg / "tests").exists(), "tests must not ship")

    def test_asset_manifest_references_existing_files(self) -> None:
        dist = self.pkg / "backend" / "app" / "static" / "dist"
        index = dist / "index.html"
        self.assertTrue(index.is_file())
        html = index.read_text(encoding="utf-8")
        refs = re.findall(r'(?:src|href)="([^"]+)"', html)
        self.assertTrue(refs, "index.html references no assets")
        for ref in refs:
            clean = ref.lstrip("/").split("?")[0].split("#")[0]
            if not clean:
                continue
            self.assertTrue(
                (dist / clean).is_file(),
                f"asset manifest references missing file: {ref}",
            )


if __name__ == "__main__":
    unittest.main()
