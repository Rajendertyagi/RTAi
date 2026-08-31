"""Real OpenCode server adapter integration (credential-free, S1-S12).

Runs the real ``OpenCodeServerAdapter`` against the real ``opencode serve``
child.  No fakes for the happy path.  Skipped when no real binary is
available.

Assertions map 1:1 to the plan matrix in ``docs/ROADMAP.md`` section 4.
"""

from __future__ import annotations

import asyncio
import contextlib
import subprocess
import unittest
from pathlib import Path

from app.agents.opencode.server_adapter import OpenCodeServerAdapter

from .helpers import make_temp_project_dir, require_opencode_bin


async def _noop(event: dict[str, object]) -> None:
    """Awaitable no-op emit callback (Emit protocol)."""


class RealServerAdapterTests(unittest.IsolatedAsyncioTestCase):
    """Credential-free server adapter tests against the real ``opencode serve``."""

    def setUp(self) -> None:
        self.bin = require_opencode_bin()
        self._tmp = make_temp_project_dir()
        self.cwd = Path(self._tmp.name)
        self.adapter: OpenCodeServerAdapter | None = None

    async def asyncTearDown(self) -> None:
        if self.adapter is not None and self.adapter.owned_process() is not None:
            await self.adapter.close()
        self._tmp.cleanup()

    # -- helpers ---------------------------------------------------------------

    async def _build(self) -> OpenCodeServerAdapter:
        """Start a fresh adapter and return it (also stored for tearDown)."""
        adapter = OpenCodeServerAdapter(opencode_bin=self.bin)
        await adapter.start(cwd=self.cwd, emit=_noop)
        self.adapter = adapter
        return adapter

    # -- S1: binary discovery and version --------------------------------------

    async def test_s1_binary_version(self) -> None:
        proc = subprocess.run(
            [self.bin, "--version"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        combined = proc.stdout + proc.stderr
        self.assertIn("1.18.21", combined)

    # -- S2: owned-process startup ---------------------------------------------

    async def test_s2_owned_process_startup(self) -> None:
        adapter = await self._build()
        owned = adapter.owned_process()
        self.assertIsNotNone(owned)
        self.assertIsNotNone(owned.pid)

    # -- S3: /global/health returns 200 + healthy ------------------------------

    async def test_s3_global_health(self) -> None:
        adapter = await self._build()
        plan = adapter._plan
        assert plan is not None
        result = await adapter._http.request(
            "GET",
            f"{plan.base_url}/global/health",
            headers=adapter._headers(),
        )
        self.assertEqual(result.status, 200)
        payload = result.json() or {}
        self.assertTrue(payload.get("healthy"))

    # -- S4: Basic authentication enforced -------------------------------------

    async def test_s4_basic_auth_enforced(self) -> None:
        adapter = await self._build()
        plan = adapter._plan
        assert plan is not None
        # Request without Authorization header -> rejected.
        result = await adapter._http.request(
            "GET",
            f"{plan.base_url}/global/health",
        )
        self.assertIn(result.status, (401, 403))

    # -- S5: runtime capability snapshot is well-formed -------------------------

    async def test_s5_capability_snapshot(self) -> None:
        adapter = await self._build()
        snap = adapter.capability_snapshot()
        self.assertEqual(snap.source, "opencode-server")
        # Sections are populated (available or unavailable-with-reason).
        self.assertIsNotNone(snap.models)
        self.assertIsNotNone(snap.commands)
        self.assertIsNotNone(snap.modes)

    # -- S6+S7: /event SSE connection established with correct content type ----

    async def test_s6_s7_sse_stream(self) -> None:
        adapter = await self._build()
        # The adapter's _consume_events opens an SSE stream to /event.
        # Prove the connection was established and is actively reading:
        #   S6: stream task is running (would have failed with bad_content_type)
        #   S7: the reader thread is alive (incremental delivery in progress)
        self.assertIsNotNone(adapter._stream_task)
        self.assertFalse(adapter._stream_task.done())  # type: ignore[union-attr]
        # Give the stream task time to connect and start the reader thread.
        await asyncio.sleep(2)
        thread = adapter._http._active_reader_thread  # noqa: SLF001
        self.assertIsNotNone(thread, "SSE reader thread should be alive")
        self.assertTrue(thread.is_alive())  # type: ignore[union-attr]

    # -- S8: session created with non-empty id ---------------------------------

    async def test_s8_session_created(self) -> None:
        adapter = await self._build()
        self.assertIsInstance(adapter._session_id, str)
        self.assertGreater(len(adapter._session_id), 0)

    # -- S9: session abort completes without killing the process ----------------

    async def test_s9_session_abort_completes(self) -> None:
        adapter = await self._build()
        # Abort with no active prompt; must not hang and must not kill
        # the process.  Do not assume HTTP 204.
        with contextlib.suppress(RuntimeError):
            await asyncio.wait_for(adapter.cancel(), timeout=20)
        owned = adapter.owned_process()
        self.assertIsNotNone(owned)
        # The subprocess is still alive (returncode not yet set).
        if owned is not None:
            self.assertIsNone(owned._handle.returncode)  # noqa: SLF001

    # -- S10: adapter close returns without exception --------------------------

    async def test_s10_shutdown(self) -> None:
        adapter = await self._build()
        await adapter.close()
        # close() completed; no exception.

    # -- S11: SSE reader thread terminated after close -------------------------

    async def test_s11_reader_thread_terminated(self) -> None:
        adapter = await self._build()
        # Let the stream task start and create the reader thread.
        await asyncio.sleep(2)
        thread = adapter._http._active_reader_thread  # noqa: SLF001
        self.assertIsNotNone(thread, "reader thread should have started")
        self.assertTrue(thread.is_alive(), "reader thread should be alive")
        await adapter.close()
        # _active_reader_thread is never reset to None; assert it is dead.
        self.assertFalse(thread.is_alive())  # type: ignore[union-attr]

    # -- S12: owned-process reference cleared after close ----------------------

    async def test_s12_owned_process_cleared(self) -> None:
        adapter = await self._build()
        self.assertIsNotNone(adapter.owned_process())
        await adapter.close()
        self.assertIsNone(adapter.owned_process())


if __name__ == "__main__":
    unittest.main()
