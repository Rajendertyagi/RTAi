"""OpenCode adapter behavior without ever launching OpenCode.

The pinned SDK module is replaced by an in-memory fake so ``start`` can be
driven end-to-end offline: spawn -> initialize -> new_session, including the
partial-startup cleanup path. The binary resolution step is stubbed with a
fake path, so no executable can ever run.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest import mock

from app.agents.capabilities import (
    AgentDescriptor,
    UnavailabilityReason,
    UnavailableCapability,
)
from app.agents.opencode_acp import OpenCodeSession

FAKE_BIN = "C:/fake/bin/opencode.exe"


class FakeProcess:
    def __init__(self) -> None:
        self.pid = 4321
        self.kill_calls = 0

    def kill(self) -> None:
        self.kill_calls += 1


class FakeContext:
    def __init__(self, connection: FakeConnection, process: FakeProcess) -> None:
        self.connection = connection
        self.process = process
        self.exit_calls = 0

    async def __aenter__(self) -> tuple[FakeConnection, FakeProcess]:
        return self.connection, self.process

    async def __aexit__(self, *exc: object) -> None:
        self.exit_calls += 1


class FakeConnection:
    def __init__(
        self, fail_new_session: bool = False, agent_info: Any | None = ...
    ) -> None:
        self.fail_new_session = fail_new_session
        self.initialize_kwargs: dict[str, Any] | None = None
        self.new_session_kwargs: dict[str, Any] | None = None
        self._agent_info = (
            agent_info
            if agent_info is not ...
            else FakeConnection._Info()
        )

    class _Info:
        name = "opencode"
        version = "1.18.23"

    async def initialize(self, **kwargs: Any) -> Any:
        self.initialize_kwargs = kwargs

        class Response:
            agentInfo = self._agent_info
            protocolVersion = 1

        return Response()

    async def new_session(self, **kwargs: Any) -> Any:
        if self.fail_new_session:
            raise RuntimeError("boom during new_session")
        self.new_session_kwargs = kwargs

        class Session:
            session_id = "session-owned-1"

        return Session()


def install_fake_acp(context: FakeContext) -> None:
    """Replace sys.modules['acp'] with a fake that always yields ``context``."""

    def spawn_agent_process(
        to_client: object, command: str, *args: str, **kwargs: Any
    ) -> FakeContext:
        assert command == FAKE_BIN
        assert list(args) == ["acp"]
        return context

    fake = ModuleType("acp")
    fake.PROTOCOL_VERSION = 1  # type: ignore[attr-defined]
    fake.spawn_agent_process = spawn_agent_process  # type: ignore[attr-defined]
    interfaces = ModuleType("acp.interfaces")
    interfaces.Client = object  # type: ignore[attr-defined]
    sys.modules["acp"] = fake
    sys.modules["acp.interfaces"] = interfaces


class OpenCodeAdapterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.cwd = Path(os.getcwd()).resolve()
        env_patcher = mock.patch.dict(os.environ, {"OPENCODE_BIN": ""})
        env_patcher.start()
        self.addCleanup(env_patcher.stop)

    def resolve_via_fake_path(self) -> None:
        which_patcher = mock.patch("shutil.which", return_value=FAKE_BIN)
        which_patcher.start()
        self.addCleanup(which_patcher.stop)

    async def test_snapshot_before_start_invents_nothing(self) -> None:
        snap = OpenCodeSession().capability_snapshot()
        for section in (snap.models, snap.modes, snap.thinking_options, snap.commands):
            self.assertEqual(section.items, ())
            reason = section.unavailable
            assert reason is not None
            self.assertEqual(reason.reason, UnavailabilityReason.PENDING_DISCOVERY)
        self.assertIsInstance(snap.attachments, UnavailableCapability)
        self.assertIsInstance(snap.sessions, UnavailableCapability)

    async def test_missing_binary_raises_without_spawning(self) -> None:
        which_patcher = mock.patch("shutil.which", return_value=None)
        which_patcher.start()
        self.addCleanup(which_patcher.stop)
        session = OpenCodeSession()
        with self.assertRaisesRegex(RuntimeError, "OpenCode was not found"):
            await session.start(self.cwd, emit=self._noop_emit)
        self.assertIsNone(session.owned_process())

    async def test_start_captures_identity_and_session_ownership(self) -> None:
        self.resolve_via_fake_path()
        context = FakeContext(FakeConnection(), FakeProcess())
        install_fake_acp(context)
        session = OpenCodeSession()
        emitted: list[dict[str, Any]] = []
        await session.start(self.cwd, emit=emitted.append)

        owned = session.owned_process()
        self.assertIsNotNone(owned)
        assert owned is not None
        self.assertEqual(owned.pid, 4321)
        self.assertEqual(owned.session_id, "session-owned-1")
        self.assertEqual(owned.argv, (FAKE_BIN, "acp"))

        snapshot = session.capability_snapshot()
        self.assertEqual(snapshot.source, "acp:opencode")
        self.assertIsInstance(snapshot.agent, AgentDescriptor)
        agent = snapshot.agent
        assert isinstance(agent, AgentDescriptor)
        self.assertEqual(agent.label, "opencode")
        # Session state carried no config options in this fake: slices stay
        # empty-but-available rather than pending.
        self.assertTrue(snapshot.models.is_empty_but_available)
        self.assertEqual(
            connection_kwargs_of(context).get("protocol_version"), 1
        )
        new_kwargs = connection_kwargs_of(context)["new_session"]
        assert new_kwargs is not None
        self.assertEqual(new_kwargs.get("cwd"), str(self.cwd))

        await session.close()
        self.assertIsNone(session.owned_process())
        self.assertEqual(context.exit_calls, 1)
        self.assertEqual(context.process.kill_calls, 0)

    async def test_agent_info_none_falls_back_to_opencode(self) -> None:
        """When the provider returns agentInfo=None, the adapter falls back
        to the documented default identity ``opencode`` rather than inventing
        metadata or leaving the agent unavailable."""
        self.resolve_via_fake_path()
        context = FakeContext(
            FakeConnection(agent_info=None), FakeProcess()
        )
        install_fake_acp(context)
        session = OpenCodeSession()
        emitted: list[dict[str, Any]] = []
        await session.start(self.cwd, emit=emitted.append)

        snapshot = session.capability_snapshot()
        self.assertIsInstance(snapshot.agent, AgentDescriptor)
        self.assertEqual(snapshot.agent.label, "opencode")
        self.assertEqual(snapshot.agent.id, "opencode")
        self.assertEqual(snapshot.source, "acp:opencode")

        # No version should be invented when the provider omits it.
        self.assertIsNone(session._agent_version)

        await session.close()
        self.assertIsNone(session.owned_process())

    async def test_partial_startup_failure_cleans_only_owned_resources(self) -> None:
        self.resolve_via_fake_path()
        connection = FakeConnection(fail_new_session=True)
        process = FakeProcess()
        context = FakeContext(connection, process)
        install_fake_acp(context)
        session = OpenCodeSession()
        with self.assertRaisesRegex(RuntimeError, "boom during new_session"):
            await session.start(self.cwd, emit=self._noop_emit)
        # Cooperative context shutdown ran exactly once; no forced kill needed.
        self.assertEqual(context.exit_calls, 1)
        self.assertEqual(process.kill_calls, 0)
        self.assertIsNone(session.owned_process())

    @staticmethod
    async def _noop_emit(event: dict[str, Any]) -> None:
        return None


def connection_kwargs_of(context: FakeContext) -> dict[str, dict[str, Any]]:
    connection = context.connection
    return {
        "protocol_version": (connection.initialize_kwargs or {}).get("protocol_version"),
        "new_session": connection.new_session_kwargs,
    }


if __name__ == "__main__":
    unittest.main()
