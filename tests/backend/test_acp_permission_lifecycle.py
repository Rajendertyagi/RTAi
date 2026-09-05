"""Exactly ONE approval card per active permission id (no duplicate cards).

Regression guard for Part 2. The ACP ``tool_start`` event and the
``permission_request`` event are correlated ONLY by the exact ``toolCallId``.
Concurrent/interleaved tool calls make any "last tool call" or
"most-recent unmatched tool" heuristic unsafe, so the projector never falls
back to one. The tests below pin the corrected behavior:

* matching ``toolCallId``  -> the single tool-call part gains the approval;
* divergent ``toolCallId`` -> a SEPARATE part is created for the permission
  (it must NOT be merged into the unrelated ``tool-abc`` part);
* identical permission id redelivered -> the same part is updated, never
  duplicated;
* permission arriving first -> one buffered part keyed by its real toolCallId,
  and the later ``tool_start`` merges into it (still one card).

If ACP supplies no usable toolCallId the client synthesizes a permission-
scoped id and the projector renders exactly one safe, non-actionable card;
that path is covered by the adapter-level contract, not re-tested here.
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
                    "tool_call_id": "tool-abc",  # exact match
                    "options": [
                        {"id": "allow-once", "label": "Allow", "kind": "allow_once"}
                    ],
                    "title": "fs",
                    "kind": "fs",
                },
            ],
        )
        parts = tool_call_parts(ctrl)
        self.assertEqual(len(parts), 1, "tool part should not be duplicated")
        self.assertEqual(parts[0]["toolCallId"], "tool-abc")
        self.assertEqual(parts[0]["approval"]["id"], "perm-1")
        self.assertEqual(parts[0]["approval"]["options"][0]["id"], "allow-once")

    async def test_divergent_tool_call_id_keeps_separate_parts(self) -> None:
        # The permission carries a divergent id (tc-perm-1) from the tool_start
        # part (tool-abc). The projector must NOT merge the approval into the
        # unrelated tool part; instead it creates exactly one additional part
        # keyed by the real permission toolCallId. This is the corrected
        # behavior that replaces the unsafe "last unmatched tool" merge.
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
                    "tool_call_id": "tc-perm-1",  # divergent id
                    "options": [
                        {"id": "allow-once", "label": "Allow", "kind": "allow_once"}
                    ],
                    "title": "fs",
                    "kind": "fs",
                },
            ],
        )
        parts = tool_call_parts(ctrl)
        self.assertEqual(len(parts), 2, "divergent permission must not merge into tool-abc")
        tool_part = next(p for p in parts if p["toolCallId"] == "tool-abc")
        perm_part = next(p for p in parts if p["toolCallId"] == "tc-perm-1")
        # The unrelated tool part stays free of any approval.
        self.assertNotIn("approval", tool_part)
        # Exactly one approval card, keyed by its own toolCallId.
        self.assertEqual(perm_part["approval"]["id"], "perm-1")

    async def test_idempotent_redelivery_keeps_single_part(self) -> None:
        # Delivering the same permission id twice (with the same toolCallId)
        # must update the existing part, never create a second card.
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
        await emit(dispatch, [perm, perm])  # deliver the same permission twice
        parts = tool_call_parts(ctrl)
        self.assertEqual(len(parts), 1, "redelivery must not duplicate the card")
        self.assertEqual(parts[0]["toolCallId"], "tc-perm-1")
        self.assertEqual(parts[0]["approval"]["id"], "perm-1")
        # Still exactly one pending approval, never duplicated.
        self.assertIsNone(parts[0]["approval"].get("approved"))

    async def test_permission_first_buffers_single_part(self) -> None:
        # Permission arrives before the tool_start that will carry the same
        # toolCallId. The projector must buffer exactly one part keyed by the
        # real toolCallId, and the later tool_start must merge into it — still
        # one card, never two.
        ctrl, dispatch = build_dispatch()
        await emit(
            dispatch,
            [
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
                {
                    "type": "tool_start",
                    "tool_call_id": "tool-abc",
                    "toolName": "fs",
                    "raw_input": {"cmd": "rm -rf /tmp/x"},
                },
            ],
        )
        parts = tool_call_parts(ctrl)
        self.assertEqual(len(parts), 1, "permission-first must yield one merged card")
        self.assertEqual(parts[0]["toolCallId"], "tool-abc")
        self.assertEqual(parts[0]["approval"]["id"], "perm-1")


if __name__ == "__main__":
    unittest.main()
