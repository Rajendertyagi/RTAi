"""Real OpenCode ACP adapter integration (credential-free, A1-A9).

Runs the real ``OpenCodeSession`` (ACP adapter) against the real
``opencode acp`` child over stdio.  No fakes for the happy path.  Skipped
when no real binary is available.

A7 (never list/load/resume sessions) is a STATIC invariant, not a runtime
assertion — see ``TestNoSessionReuseStatic`` at the bottom of this file.
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path

from app.agents.opencode_acp import OpenCodeSession

from .helpers import make_temp_project_dir, require_opencode_bin


async def _noop(event: dict[str, object]) -> None:
    """Awaitable no-op emit callback (Emit protocol)."""


class RealAcpAdapterTests(unittest.IsolatedAsyncioTestCase):
    """Credential-free ACP adapter tests against the real ``opencode acp``."""

    def setUp(self) -> None:
        self.bin = require_opencode_bin()
        self._tmp = make_temp_project_dir()
        self.cwd = Path(self._tmp.name)
        self.adapter: OpenCodeSession | None = None

    async def asyncTearDown(self) -> None:
        if self.adapter is not None:
            await self.adapter.close()
        self._tmp.cleanup()

    # -- helpers ---------------------------------------------------------------

    async def _build(self) -> OpenCodeSession:
        """Start a fresh ACP adapter and return it (stored for tearDown)."""
        adapter = OpenCodeSession()
        # Ensure the adapter resolves to the pinned binary.
        os.environ["OPENCODE_BIN"] = self.bin
        await adapter.start(cwd=self.cwd, emit=_noop)
        self.adapter = adapter
        return adapter

    # -- A1: owned stdio subprocess started ------------------------------------

    async def test_a1_owned_subprocess_started(self) -> None:
        adapter = await self._build()
        owned = adapter.owned_process()
        self.assertIsNotNone(owned)
        self.assertIsNotNone(owned.pid)

    # -- A2: protocol initialization succeeds ----------------------------------

    async def test_a2_initialize_succeeds(self) -> None:
        adapter = await self._build()
        self.assertTrue(adapter._initialized)

    # -- A3: returned agent identity is real -----------------------------------

    async def test_a3_agent_identity_real(self) -> None:
        from app.agents.capabilities import AgentDescriptor

        adapter = await self._build()
        snap = adapter.capability_snapshot()
        # agent_info is optional per the ACP spec; the adapter falls back to
        # the string "opencode" so the snapshot always exposes a non-empty
        # AgentDescriptor rather than an unavailable-capability placeholder.
        self.assertIsInstance(snap.agent, AgentDescriptor)
        self.assertGreater(len(snap.agent.id), 0)
        self.assertGreater(len(snap.agent.label), 0)

    # -- A4: capability negotiation succeeds -----------------------------------

    async def test_a4_capability_negotiation(self) -> None:
        adapter = await self._build()
        snap = adapter.capability_snapshot()
        self.assertTrue(snap.source.startswith("acp:"))
        # Source includes the agent name (e.g. "acp:opencode").
        self.assertIn("opencode", snap.source)

    # -- A5: session id is non-empty (no prefix requirement) -------------------

    async def test_a5_session_id_nonempty(self) -> None:
        adapter = await self._build()
        self.assertIsInstance(adapter._session_id, str)
        self.assertGreater(len(adapter._session_id), 0)

    # -- A6: runtime config options mapped without invention -------------------

    async def test_a6_no_invented_capabilities(self) -> None:
        adapter = await self._build()
        snap = adapter.capability_snapshot()
        # Without a provider, models must be unavailable-with-reason,
        # never invented.  Verify no hardcoded test value appears.
        if snap.models.available:
            model_ids = [m.id for m in snap.models.items]
            self.assertNotIn("anthropic/claude-sonnet-4", model_ids)

    # -- A8: clean adapter/context/process shutdown ----------------------------

    async def test_a8_clean_shutdown(self) -> None:
        adapter = await self._build()
        await adapter.close()  # must not raise
        self.assertIsNone(adapter.owned_process())

    # -- A9: owned-process reference cleared -----------------------------------

    async def test_a9_owned_process_cleared(self) -> None:
        adapter = await self._build()
        self.assertIsNotNone(adapter.owned_process())
        await adapter.close()
        self.assertIsNone(adapter.owned_process())


# ---------------------------------------------------------------------------
# A7 — static invariant: never list/load/resume sessions
# ---------------------------------------------------------------------------

class TestNoSessionReuseStatic(unittest.TestCase):
    """A7: the adapter source never calls list/load/resume_session.

    This is a code-level invariant enforced by inspection, not by a runtime
    mock spy.  It runs without a real OpenCode binary (no SkipTest).
    """

    def test_no_list_load_resume_calls(self) -> None:
        import re

        source = (
            Path(__file__).resolve().parents[2]
            / "backend"
            / "app"
            / "agents"
            / "opencode_acp.py"
        )
        text = source.read_text(encoding="utf-8")
        # Match method-call patterns only: .load_session( or load_session(
        # deliberately excludes variable names like _load_session_cap.
        forbidden = ("list_sessions", "load_session", "resume_session")
        for name in forbidden:
            pattern = rf"\b{name}\s*\("
            self.assertIsNone(
                re.search(pattern, text),
                f"OpenCodeAcpAdapter must not call {name}() "
                f"(ownership invariant, ADR-0006).",
            )


if __name__ == "__main__":
    unittest.main()
