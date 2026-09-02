"""Exactly ONE approval card per active permission id (no duplicate cards).

The ACP ``tool_start`` event carries the real tool call id (e.g. ``tool-abc``),
while the ``permission_request`` event derives its id from the SDK tool call and
can fall back to a divergent id (``tc-permN``) when that object lacks one. The
projector must correlate the permission with the existing tool-start part instead
of spawning a second tool-call part, so the UI renders a single card and the
official ToolFallback auto-expands it. This is the regression guard for Issue 2.
"""
from __future__ import annotations

import unittest


class _StubController:
    """Minimal stand-in for RunController: the projector only needs a mutable
    ``.state`` dict plus no-op flush/append_state_text."""

    def __init__(self, state: dict) -> None:
        self.state = state

    def flush(self) -> None:
        pass

    def append_state_text(self, *args, **kwargs) -> None:
        pass


def build_dispatch():
    from app.transport.assistant.acp_state_projector import AcpStateProjector
    from app.transport.assistant.session_manager import (
        AssistantTransportDispatch,
        PermissionRegistry,
    )

    ctrl = _StubController({"messages": [], "status": "running"})
    dispatch = AssistantTransportDispatch()
    dispatch.permissions = PermissionRegistry()
    proj = AcpStateProjector(ctrl, session_key="sess1")
    dispatch.bind(proj)
    return ctrl, dispatch


def tool_call_parts(ctrl):
    parts = []
    for msg in ctrl.state["messages"]:
        for part in msg["parts"]:
            if part.get("type") == "tool-call":
                parts.append(part)
    return parts


async def emit(dispatch, events):
    for ev in events:
        await dispatch(ev)


class PermissionLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_divergent_tool_call_id_yields_single_part(self) -> None:
        ctrl, dispatch = build_dispatch()
        await emit(
            dispatch,
            [
                {
                    "type": "tool_start",
                    "tool_call_id": "tool-abc",
                    "toolName": "fs",
                    "raw_input": {"cmd": "rm -rf /tmp/x"},
                },
                {
                    "type": "permission_request",
                    "permission_request_id": "perm-1",
                    "tool_call_id": "tc-perm-1",  # divergent fallback id
                    "options": [
                        {"id": "allow-once", "label": "Allow", "kind": "allow_once"}
                    ],
                    "title": "fs",
                    "kind": "fs",
                },
            ],
        )
        parts = tool_call_parts(ctrl)
        self.assertEqual(len(parts), 1, "duplicate tool-call part created")
        self.assertEqual(parts[0]["toolCallId"], "tool-abc")
        self.assertEqual(parts[0]["approval"]["id"], "perm-1")
        self.assertEqual(parts[0]["approval"]["options"][0]["id"], "allow-once")

    async def test_matching_tool_call_id_yields_single_part(self) -> None:
        ctrl, dispatch = build_dispatch()
        await emit(
            dispatch,
            [
                {
                    "type": "tool_start",
                    "tool_call_id": "tool-abc",
                    "toolName": "fs",
                    "raw_input": {"cmd": "rm -rf /tmp/x"},
                },
                {
                    "type": "permission_request",
                    "permission_request_id": "perm-1",
                    "tool_call_id": "tool-abc",
                    "options": [
                        {"id": "allow-once", "label": "Allow", "kind": "allow_once"}
                    ],
                    "title": "fs",
                    "kind": "fs",
                },
            ],
        )
        self.assertEqual(len(tool_call_parts(ctrl)), 1)

    async def test_idempotent_redelivery_keeps_single_part(self) -> None:
        ctrl, dispatch = build_dispatch()
        perm = {
            "type": "permission_request",
            "permission_request_id": "perm-1",
            "tool_call_id": "tc-perm-1",
            "options": [
                {"id": "allow-once", "label": "Allow", "kind": "allow_once"}
            ],
            "title": "fs",
            "kind": "fs",
        }
        await emit(
            dispatch,
            [
                {
                    "type": "tool_start",
                    "tool_call_id": "tool-abc",
                    "toolName": "fs",
                    "raw_input": {"cmd": "rm -rf /tmp/x"},
                },
                perm,
                perm,  # deliver the same permission twice
            ],
        )
        parts = tool_call_parts(ctrl)
        self.assertEqual(len(parts), 1)
        # Still exactly one pending approval, never duplicated.
        self.assertIsNone(parts[0]["approval"].get("approved"))


if __name__ == "__main__":
    unittest.main()
