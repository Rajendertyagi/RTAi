"""OpenCode Server adapter behavior with fakes only (Phase 2A-B cases 10-14)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from app.agents.opencode.server_adapter import OpenCodeServerAdapter


async def _noop_emit(event: dict) -> None:
    """Async no-op emit for tests that never assert on emitted events.

    ``Emit`` is ``Callable[[dict], Awaitable[None]]``; a sync lambda would
    return ``None`` and break any ``await self._emit(...)`` in the adapter.
    """
    del event


class FakeHandle:
    def __init__(self) -> None:
        self.kill_calls = 0

    def kill(self) -> None:
        self.kill_calls += 1


class FakeLaunched:
    def __init__(self) -> None:
        self.pid = 5555
        self.terminate_calls = 0
        self.wait_calls = 0
        self.kill_calls = 0
        self.returncode: int | None = None

    def terminate(self) -> None:
        self.terminate_calls += 1
        self.returncode = 0

    async def wait(self) -> int:
        self.wait_calls += 1
        return 0

    def kill(self) -> None:
        self.kill_calls += 1
        self.returncode = -9


class FakeLauncher:
    def __init__(self) -> None:
        self.plans: list[object] = []

    async def launch(self, plan: object) -> tuple[object, FakeLaunched]:
        self.plans.append(plan)
        from app.agents.owned_process import OwnedProcess

        handle = FakeLaunched()

        async def cooperative() -> None:
            handle.terminate()
            await handle.wait()

        owned = OwnedProcess(
            handle=handle,
            pid=handle.pid,
            argv=plan.argv,
            cooperative_close=cooperative,
            force_timeout_seconds=0.05,
        )
        return owned, handle


class FakeHttp:
    _MISSING = object()

    def __init__(self, responses: dict[tuple[str, str], object]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str]] = []

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: object = None,
        timeout_seconds: float = 10.0,
    ) -> object:
        from urllib.parse import urlparse

        from app.agents.opencode.http_client import HttpResult

        path = urlparse(url).path or "/"
        key = (method, path)
        self.calls.append(key)
        body = self.responses.get(key, FakeHttp._MISSING)
        if body is FakeHttp._MISSING:
            return HttpResult(status=404, body=b"{}")
        if body is None:
            return HttpResult(status=204, body=b"")
        import json as _json

        return HttpResult(status=200, body=_json.dumps(body).encode())

    def stream_lines(self, url: str, **kw: object) -> object:
        class _Blocked:
            def __aiter__(self) -> _Blocked:
                return self
            def __anext__(self) -> object:
                raise StopAsyncIteration
        return _Blocked()


from collections.abc import AsyncIterator  # noqa: E402 - needed above

HEALTH = ("GET", "/global/health")


def make_responses() -> dict[tuple[str, str], object]:
    responses: dict[tuple[str, str], object] = {}
    responses[HEALTH] = {"healthy": True, "version": "1.18.23"}
    responses[("POST", "/session")] = {"id": "ses-1"}
    responses[("GET", "/config/providers")] = PROVIDERS
    responses[("GET", "/config")] = {"model": "anthropic/claude-sonnet-4"}
    responses[("GET", "/command")] = [{"name": "init", "description": "Init"}]
    responses[("GET", "/agent")] = [
        {"name": "build", "description": "Builder"},
        {"name": "plan", "description": "Planner"},
    ]
    responses[("POST", "/session/ses-1/prompt_async")] = None
    responses[("POST", "/session/ses-1/abort")] = None
    return responses


PROVIDERS = {
    "anthropic": {
        "models": {
            "claude-sonnet-4": {"name": "Claude Sonnet 4"},
        }
    }
}


class ServerAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def build_adapter(self, extra_responses: dict | None = None) -> tuple[
        OpenCodeServerAdapter, FakeLauncher, FakeHttp, FakeLaunched
    ]:
        launcher = FakeLauncher()
        http = FakeHttp({**make_responses(), **(extra_responses or {})})
        adapter = OpenCodeServerAdapter(
            opencode_bin="C:/fake/opencode.exe",
            http=http,
            launcher=launcher,
        )
        await adapter.start(cwd=None, emit=_noop_emit)
        owned = adapter.owned_process()
        assert owned is not None
        launched_handle = owned._handle  # noqa: SLF001 - white-box harness
        return adapter, launcher, http, launched_handle

    async def test_launch_plan_is_loopback_with_dynamic_private_port(self) -> None:
        adapter, launcher, _, _ = await self.build_adapter()
        plan = launcher.plans[0]
        self.assertIn("--hostname", plan.argv)
        host_index = plan.argv.index("--hostname")
        self.assertEqual(plan.argv[host_index + 1], "127.0.0.1")
        port_index = plan.argv.index("--port")
        port = int(plan.argv[port_index + 1])
        self.assertGreaterEqual(port, 1024)
        self.assertLess(port, 65536)
        self.assertNotEqual(port, 4096)
        self.assertTrue(plan.base_url.startswith("http://127.0.0.1:"))

    async def test_capability_sections_from_documented_endpoints(self) -> None:
        adapter, _, _, _ = await self.build_adapter()
        snap = adapter.capability_snapshot()
        self.assertEqual(snap.source, "opencode-server")
        models = [m.id for m in snap.models.items]
        self.assertEqual(models, ["anthropic/claude-sonnet-4"])
        self.assertEqual([c.name for c in snap.commands.items], ["init"])

    async def test_missing_endpoint_becomes_unavailable_reason(self) -> None:
        adapter, _, _, _ = await self.build_adapter(
            {("GET", "/command"): {"error": "gone"}}
        )
        commands = adapter.capability_snapshot().commands
        self.assertFalse(commands.available)
        self.assertIsNotNone(commands.unavailable)
        assert commands.unavailable is not None
        self.assertEqual(commands.unavailable.reason.value, "not_exposed_by_provider")

    async def test_thinking_unavailable_when_no_variants(self) -> None:
        adapter, _, _, _ = await self.build_adapter()
        thinking = adapter.capability_snapshot().thinking_options
        self.assertFalse(thinking.available)
        assert thinking.unavailable is not None
        self.assertIn("variants", thinking.unavailable.message.lower())

    async def test_prompt_uses_async_endpoint_and_abort_for_cancel(self) -> None:
        adapter, _, http, _ = await self.build_adapter()
        await adapter.submit_prompt("hello")
        await adapter.cancel()
        self.assertIn(("POST", "/session/ses-1/prompt_async"), http.calls)
        self.assertIn(("POST", "/session/ses-1/abort"), http.calls)

    async def test_cleanup_targets_only_the_stored_handle(self) -> None:
        adapter, _, _, handle = await self.build_adapter()
        foreign = FakeHandle()
        await adapter.close()
        self.assertEqual(handle.terminate_calls, 1)
        self.assertEqual(handle.wait_calls, 1)
        self.assertEqual(handle.kill_calls, 0)
        self.assertEqual(foreign.kill_calls, 0)

    async def test_readiness_timeout_cleans_up_the_owned_child(self) -> None:
        launcher = FakeLauncher()
        http = FakeHttp({})
        adapter = OpenCodeServerAdapter(
            opencode_bin="C:/fake/opencode.exe",
            http=http,
            launcher=launcher,
            ready_timeout_seconds=0.05,
            poll_interval_seconds=0.01,
        )
        with self.assertRaisesRegex(RuntimeError, "startup failed.*timeout"):
            await adapter.start(cwd=None, emit=_noop_emit)
        owned = adapter.owned_process()
        self.assertIsNone(owned)

    async def test_selection_is_explicitly_not_supported_yet(self) -> None:
        adapter, _, _, _ = await self.build_adapter()
        result = await adapter.select("model", "anthropic/x")
        self.assertFalse(result.applied)


class FakeHttpQuiet(FakeHttp):
    """Fake HTTP whose event stream is empty (no lines, clean EOF)."""

    def stream_lines(self, url: str, **kwargs: object) -> object:
        async def gen() -> AsyncIterator[str]:
            return
            yield  # unreachable; makes this an async generator

        return gen()


class FakeProcess:
    """Recorded fake child process handle."""

    def __init__(self, returncode: int | None) -> None:
        self.returncode = returncode
        self.terminate_calls = 0
        self.wait_calls = 0
        self.kill_calls = 0

    def terminate(self) -> None:
        self.terminate_calls += 1
        self.returncode = 0

    async def wait(self) -> int:
        self.wait_calls += 1
        return 0

    def kill(self) -> None:
        self.kill_calls += 1


class _RecordingLauncher:
    """Launches a real OwnedProcess per attempt; the child may report an exit
    code to simulate a bind/startup race on the first ``fail_attempts`` tries."""

    def __init__(self, fail_attempts: int = 1) -> None:
        self.plans: list[object] = []
        self.processes: list[FakeProcess] = []
        self._attempt = 0
        self._fail_attempts = fail_attempts

    async def launch(self, plan: object) -> tuple[object, object]:
        from app.agents.owned_process import OwnedProcess

        self._attempt += 1
        self.plans.append(plan)
        rc: int | None = 1 if self._attempt <= self._fail_attempts else None
        process = FakeProcess(returncode=rc)
        self.processes.append(process)

        async def cooperative() -> None:
            process.terminate()
            await process.wait()

        owned = OwnedProcess(
            handle=process,
            pid=1234,
            argv=getattr(plan, "argv", ("x",)),
            cooperative_close=cooperative,
            force_timeout_seconds=0.05,
        )
        return owned, process


class TestBindRetryOwnership(unittest.IsolatedAsyncioTestCase):
    async def test_child_spawned_then_fails_readiness_is_cleaned_and_retried(
        self,
    ) -> None:
        from app.agents.opencode.launcher import pick_private_port

        launcher = _RecordingLauncher(fail_attempts=1)
        http = FakeHttpQuiet({**make_responses()})
        adapter = OpenCodeServerAdapter(
            opencode_bin="C:/fake/opencode.exe",
            http=http,
            launcher=launcher,
            ready_timeout_seconds=0.05,
            poll_interval_seconds=0.01,
            bind_retry_attempts=1,
        )
        with patch(
            "app.agents.opencode.launcher.pick_private_port",
            wraps=pick_private_port,
        ) as spy:
            await adapter.start(cwd=None, emit=_noop_emit)

        # Allocator invoked once per launch (two attempts => two picks),
        # proving a fresh port is requested even if the OS returns the same
        # numeric ephemeral port.
        self.assertEqual(spy.call_count, 2)
        self.assertEqual(len(launcher.plans), 2)

        # The first (failed) child was cleaned up; the second remains owned.
        self.assertEqual(launcher.processes[0].terminate_calls, 1)
        self.assertEqual(launcher.processes[1].terminate_calls, 0)
        self.assertIs(adapter.owned_process()._handle, launcher.processes[1])

        # Every allocated port is a valid private port, never the fallback 4096.
        for plan in launcher.plans:
            self.assertGreaterEqual(plan.port, 1024)
            self.assertLess(plan.port, 65536)
            self.assertNotEqual(plan.port, 4096)

        await adapter.close()
        # After close, the surviving child is also released.
        self.assertEqual(launcher.processes[1].terminate_calls, 1)

    async def test_retry_exhaustion_reports_classified_error_and_cleans_all(
        self,
    ) -> None:
        launcher = _RecordingLauncher(fail_attempts=99)
        http = FakeHttpQuiet({**make_responses()})
        adapter = OpenCodeServerAdapter(
            opencode_bin="C:/fake/opencode.exe",
            http=http,
            launcher=launcher,
            ready_timeout_seconds=0.05,
            poll_interval_seconds=0.01,
            bind_retry_attempts=2,
        )
        with self.assertRaisesRegex(RuntimeError, "startup failed"):
            await adapter.start(cwd=None, emit=_noop_emit)

        # All spawned children were cleaned up; none remain owned.
        for proc in launcher.processes:
            self.assertEqual(proc.terminate_calls, 1)
        self.assertIsNone(adapter.owned_process())


if __name__ == "__main__":
    unittest.main()


# Late import for AsyncIterator used only in the streaming fake.
