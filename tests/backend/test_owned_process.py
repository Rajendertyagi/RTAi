"""OwnedProcess lifecycle guarantees, proven with fake handles only."""

from __future__ import annotations

import asyncio
import unittest

from app.agents.owned_process import OwnedProcess, OwnershipState


class FakeHandle:
    """Stands in for an asyncio subprocess handle; records kill() calls."""

    def __init__(self) -> None:
        self.kill_calls = 0

    def kill(self) -> None:
        self.kill_calls += 1


class ForeignHandle(FakeHandle):
    """Anything that is NOT ours - must never be touched."""


def make_owned(
    handle: FakeHandle,
    *,
    cooperative: str = "ok",
    hang_seconds: float | None = None,
    timeout: float = 0.05,
) -> tuple[OwnedProcess, list[str]]:
    calls: list[str] = []

    async def cooperative_close() -> None:
        if hang_seconds is not None:
            await asyncio.sleep(hang_seconds)
            calls.append("timeout")  # pragma: no cover - only reached on hang
        calls.append(f"cooperative:{cooperative}")

    owned = OwnedProcess(
        handle=handle,
        pid=4242,
        argv=("opencode", "acp"),
        cooperative_close=cooperative_close,
        force_timeout_seconds=timeout,
    )
    return owned, calls


class OwnedProcessTests(unittest.IsolatedAsyncioTestCase):
    async def test_happy_path_cooperative_only(self) -> None:
        handle = FakeHandle()
        owned, calls = make_owned(handle)
        state = await owned.close()
        self.assertEqual(state, OwnershipState.CLOSED)
        self.assertEqual(calls, ["cooperative:ok"])
        self.assertEqual(handle.kill_calls, 0)

    async def test_close_is_idempotent(self) -> None:
        handle = FakeHandle()
        owned, calls = make_owned(handle)
        first = await owned.close()
        second = await owned.close()
        self.assertEqual(first, OwnershipState.CLOSED)
        self.assertEqual(second, OwnershipState.CLOSED)
        self.assertEqual(len(calls), 1)

    async def test_forced_kill_only_after_cooperative_timeout(self) -> None:
        handle = FakeHandle()
        owned, calls = make_owned(
            handle, cooperative="hangs", hang_seconds=5.0, timeout=0.02
        )
        state = await owned.close()
        self.assertEqual(state, OwnershipState.CLOSED)
        # The hung cooperative close gets cancelled by the timeout, so it must
        # never have logged completion; the stored handle is force-killed once.
        self.assertNotIn("cooperative:hangs", calls)
        self.assertEqual(handle.kill_calls, 1)
        self.assertIsNotNone(owned.last_close_error)
        self.assertIn("exceeded", owned.last_close_error or "")

    async def test_force_targets_only_the_stored_handle(self) -> None:
        handle = FakeHandle()
        foreign = ForeignHandle()
        owned, _ = make_owned(handle, cooperative="hangs", hang_seconds=5.0, timeout=0.02)
        await owned.close()
        self.assertEqual(handle.kill_calls, 1)
        self.assertEqual(foreign.kill_calls, 0)

    async def test_session_attachment_records_runtime_id(self) -> None:
        owned, _ = make_owned(FakeHandle())
        owned.attach_session("session-abc")
        self.assertEqual(owned.session_id, "session-abc")
        self.assertEqual(owned.pid, 4242)
        self.assertEqual(owned.argv, ("opencode", "acp"))

    async def test_mark_start_failed_blocks_lifecycle(self) -> None:
        owned, calls = make_owned(FakeHandle())
        owned.mark_start_failed()
        self.assertEqual(owned.state, OwnershipState.FAILED)
        result = await owned.close()
        # A failed start means nothing was fully spawned: close stays a no-op.
        self.assertEqual(result, OwnershipState.FAILED)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
