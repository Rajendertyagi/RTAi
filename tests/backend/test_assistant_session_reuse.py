"""POST /assistant session-identity lifecycle logging.

Locks the two reuse-logging guarantees fixed in this change:
- a request whose identity resolves by carrying a sessionId records EXACTLY
  one ``session.reused`` hub event with no identifier fields of any form;
- a request without any identity never claims reuse (``isNew=true`` only).

The adapter is an in-process fake: no OpenCode child, no fixed ports.
"""

from __future__ import annotations

import unittest
import uuid
from pathlib import Path
from typing import Any
from unittest import mock

from app.agents.base import AgentAdapter, Emit, SelectionResult
from app.agents.capabilities import (
    AgentDescriptor,
    CapabilitySection,
    CapabilitySnapshot,
)
from app.diagnostics import EVENT, DiagnosticsHub
from app.main import create_app
from app.transport.assistant import endpoint as assistant_endpoint
from app.transport.assistant.models import RTAI_REFRESH_COMMAND
from fastapi.testclient import TestClient


def _snapshot() -> CapabilitySnapshot:
    return CapabilitySnapshot(
        source="fake",
        agent=AgentDescriptor(id="fake", label="FakeAgent"),
        models=CapabilitySection(items=()),
        modes=CapabilitySection(items=()),
        thinking_options=CapabilitySection(items=()),
    )


class _QuietAdapter(AgentAdapter):
    """Inert adapter: creates/closes cleanly, never emits, never prompts."""

    async def start(self, cwd: Path, emit: Emit) -> None:
        return None

    async def close(self) -> None:
        return None

    def capability_snapshot(self) -> CapabilitySnapshot:
        return _snapshot()

    async def submit_prompt(self, text: str, turn_id: str = "", message_id: str = "") -> None:
        return None

    async def submit_prompt_content(
        self, content: list[Any], turn_id: str = "", message_id: str = ""
    ) -> None:
        return None

    async def cancel(self) -> None:
        return None

    def owned_process(self) -> None:
        return None

    async def select(self, kind: str, value_id: str) -> SelectionResult:
        return SelectionResult(kind=kind, applied=True, message="ok")


# Every identifier-ish field name that must never appear on a hub event.
_BANNED_FIELDS = (
    "session",
    "sid",
    "session_key",
    "sessionId",
    "session_id",
    "permission",
    "permissionId",
    "permission_id",
    "tool",
    "toolCallId",
    "tool_call_id",
    "option",
    "optionId",
    "option_id",
    "id",
    "uuid",
    "hash",
    "correlation",
)


class AssistantSessionReuseLoggingTests(unittest.TestCase):
    def _make_client(self) -> tuple[TestClient, mock.MagicMock]:
        fa = mock.MagicMock()
        fa.create.return_value = _QuietAdapter()
        return TestClient(create_app(adapter_factory=fa)), fa

    def test_identity_request_records_exactly_one_reused_event_without_ids(self) -> None:
        client, fa = self._make_client()
        hub = DiagnosticsHub()
        sid = str(uuid.uuid4())
        # A capability-refresh command is the minimal batch that reaches adapter
        # acquisition (an empty command batch returns before adapter creation).
        body = {"state": {"sessionId": sid}, "commands": [{"type": RTAI_REFRESH_COMMAND}]}
        try:
            with mock.patch.object(
                assistant_endpoint, "get_diagnostics_hub", return_value=hub
            ):
                # First request carrying the id: resolution reuses the identity
                # (and creates the adapter for that key).
                first = client.post("/assistant", json=body)
                self.assertEqual(first.status_code, 200)
                reused_after_first = self._count(hub, EVENT["SESSION_REUSED"])
                self.assertEqual(reused_after_first, 1)
                # Second request with the SAME sessionId resolves to the now
                # active session: exactly one more reused event, no new adapter.
                second = client.post("/assistant", json=body)
                self.assertEqual(second.status_code, 200)
                reused_after_second = self._count(hub, EVENT["SESSION_REUSED"])
                self.assertEqual(reused_after_second, 2)
        finally:
            client.delete(f"/assistant/sessions/{sid}")
        # The adapter was created exactly once for the reused identity.
        self.assertEqual(fa.create.call_count, 1)
        events = hub.snapshot()
        for event in events:
            for banned in _BANNED_FIELDS:
                self.assertNotIn(banned, event, f"{event['event']} leaked {banned}")
        identities = [e for e in events if e["event"] == EVENT["SESSION_IDENTITY"]]
        self.assertEqual(len(identities), 2)
        for identity in identities:
            self.assertTrue(identity["sessionIdPresent"])
            self.assertFalse(identity["threadIdPresent"])
            self.assertFalse(identity["isNew"])

    def test_request_without_identity_never_claims_reuse(self) -> None:
        client, _fa = self._make_client()
        hub = DiagnosticsHub()
        with mock.patch.object(
            assistant_endpoint, "get_diagnostics_hub", return_value=hub
        ):
            response = client.post(
                "/assistant",
                json={"state": {}, "commands": [{"type": RTAI_REFRESH_COMMAND}]},
            )
            self.assertEqual(response.status_code, 200)
        self.assertEqual(self._count(hub, EVENT["SESSION_REUSED"]), 0)
        identities = [
            e for e in hub.snapshot() if e["event"] == EVENT["SESSION_IDENTITY"]
        ]
        self.assertEqual(len(identities), 1)
        self.assertFalse(identities[0]["sessionIdPresent"])
        self.assertFalse(identities[0]["threadIdPresent"])
        self.assertTrue(identities[0]["isNew"])

    @staticmethod
    def _count(hub: DiagnosticsHub, event: str) -> int:
        return sum(1 for e in hub.snapshot() if e["event"] == event)


if __name__ == "__main__":
    unittest.main()
